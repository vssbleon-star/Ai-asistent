import sys
import asyncio
import threading
import requests
import re
from datetime import datetime
import sqlite3

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

# ==================== DATABASE ====================
class ChatDatabase:
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                role TEXT,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
    
    def save_message(self, conv_id, role, content):
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conv_id, role, content)
        )
        conn.commit()
        conn.close()
    
    def get_conversation_history(self, conv_id):
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY timestamp",
            (conv_id,)
        )
        messages = cursor.fetchall()
        conn.close()
        return [{"role": m[0], "content": m[1]} for m in messages]
    
    def create_conversation(self, title="Новый диалог"):
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO conversations (title) VALUES (?)", (title,))
        conv_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return conv_id
    
    def get_all_conversations(self):
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, title FROM conversations ORDER BY created_at DESC")
        conversations = cursor.fetchall()
        conn.close()
        return conversations
    
    def delete_conversation(self, conv_id):
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        cursor.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()
        conn.close()
    
    def clear_conversation_messages(self, conv_id):
        """Очищает все сообщения в диалоге, но оставляет сам диалог"""
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        conn.commit()
        conn.close()
    
    def save_setting(self, key, value):
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
    
    def get_setting(self, key):
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else ""

# ==================== AI ENGINE ====================
class AIEngine:
    def __init__(self):
        self.api_key = ""
        self.system_prompt = "Ты - полезный AI ассистент Danil. Отвечай на русском языке."
    
    def validate_api_key(self, api_key):
        """Проверяет валидность API ключа"""
        if not api_key:
            return True  # Пустой ключ - используется локальный режим
        
        # Проверяем формат OpenAI API ключа
        if api_key.startswith("sk-") and len(api_key) > 20:
            return True
        
        # Можно добавить проверку других форматов ключей
        # Например, для Anthropic, Google и т.д.
        
        return False
    
    async def generate_response(self, messages):
        try:
            if self.api_key and self.validate_api_key(self.api_key):
                return await self._generate_openai(messages)
            else:
                return await self._generate_local(messages)
        except Exception as e:
            return f"Ошибка: {str(e)}"
    
    async def _generate_local(self, messages):
        try:
            response = requests.post(
                "http://localhost:11434/api/chat",
                json={"model": "llama2", "messages": messages, "stream": False},
                timeout=120
            )
            if response.status_code == 200:
                return response.json()["message"]["content"]
            return "Локальная модель не запущена. Установите Ollama."
        except:
            return "Ошибка подключения к локальной модели."
    
    async def _generate_openai(self, messages):
        try:
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            data = {"model": "gpt-3.5-turbo", "messages": messages, "temperature": 0.7}
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=60)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            elif response.status_code == 401:
                return "Ошибка: Неверный API ключ. Проверьте ключ в настройках."
            return "Ошибка API OpenAI."
        except:
            return "Ошибка подключения к OpenAI."

# ==================== MAIN WINDOW ====================
class AIAssistant(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Danil AI")
        self.setGeometry(100, 100, 1400, 800)
        
        self.db = ChatDatabase()
        self.ai = AIEngine()
        self.current_conversation_id = None
        self.conversations = {}  # Кэш сообщений по ID диалога
        
        self.init_ui()
        self.load_conversations()
        
        # Если нет диалогов, создаем новый
        if self.conv_list.count() == 0:
            self.new_conversation()
        else:
            # Выбираем первый диалог из списка
            self.conv_list.setCurrentRow(0)
            self.switch_conversation(self.conv_list.item(0))
    
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(300)
        sidebar.setStyleSheet("background: #f8f9fa; border-right: 1px solid #e9ecef;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 20, 15, 20)
        sidebar_layout.setSpacing(15)
        
        title = QLabel("Danil AI")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #667eea;")
        
        new_btn = QPushButton("Новый диалог")
        new_btn.setStyleSheet("""
            QPushButton {
                background: #667eea; color: white; border: none; border-radius: 8px;
                padding: 12px; font-weight: bold; font-size: 14px;
            }
            QPushButton:hover { background: #5a6bc0; }
        """)
        new_btn.clicked.connect(self.new_conversation)
        
        delete_btn = QPushButton("Удалить диалог")
        delete_btn.setStyleSheet("""
            QPushButton {
                background: white; color: #dc3545; border: 2px solid #dc3545;
                border-radius: 6px; padding: 10px; font-weight: 500;
            }
            QPushButton:hover { background: #f8d7da; }
        """)
        delete_btn.clicked.connect(self.delete_conversation)
        
        self.conv_list = QListWidget()
        self.conv_list.setStyleSheet("""
            QListWidget {
                background: white; border: 1px solid #dee2e6; border-radius: 8px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 10px; border-bottom: 1px solid #f1f3f4;
            }
            QListWidget::item:selected {
                background: #e3f2fd; color: #1976d2; border-radius: 4px;
            }
        """)
        self.conv_list.itemClicked.connect(self.switch_conversation)
        
        settings_btn = QPushButton("Настройки")
        settings_btn.setStyleSheet("""
            QPushButton {
                background: white; color: #495057; border: 2px solid #667eea;
                border-radius: 6px; padding: 10px; font-weight: 500;
            }
            QPushButton:hover { background: #f8f9fa; }
        """)
        settings_btn.clicked.connect(self.open_settings)
        
        sidebar_layout.addWidget(title)
        sidebar_layout.addWidget(new_btn)
        sidebar_layout.addWidget(delete_btn)
        sidebar_layout.addWidget(QLabel("История диалогов:"))
        sidebar_layout.addWidget(self.conv_list, 1)
        sidebar_layout.addWidget(settings_btn)
        
        # Main area
        main_area = QWidget()
        main_area.setStyleSheet("background: white;")
        main_area_layout = QVBoxLayout(main_area)
        main_area_layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(60)
        toolbar.setStyleSheet("background: #f8f9fa; border-bottom: 1px solid #e9ecef;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(20, 0, 20, 0)
        
        model_label = QLabel("Модель:")
        model_label.setStyleSheet("color: #495057; font-weight: 500;")
        
        self.model_combo = QComboBox()
        self.model_combo.addItems(["Локальная (Llama 2)", "GPT-3.5 Turbo", "GPT-4"])
        self.model_combo.setStyleSheet("""
            QComboBox {
                background: white; border: 1px solid #ced4da; border-radius: 6px;
                padding: 8px; font-size: 13px; min-height: 36px;
            }
        """)
        
        clear_btn = QPushButton("Очистить экран")
        clear_btn.setStyleSheet("""
            QPushButton {
                background: white; color: #495057; border: 1px solid #ced4da;
                border-radius: 6px; padding: 8px 16px; font-weight: 500;
            }
            QPushButton:hover { background: #f8f9fa; }
        """)
        clear_btn.clicked.connect(self.clear_screen)
        
        toolbar_layout.addWidget(model_label)
        toolbar_layout.addWidget(self.model_combo)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(clear_btn)
        
        # Chat area
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setContentsMargins(20, 20, 20, 20)
        self.chat_layout.setSpacing(10)
        self.chat_layout.addStretch()
        
        self.chat_scroll.setWidget(self.chat_container)
        
        # Input panel
        input_panel = QWidget()
        input_panel.setMinimumHeight(160)
        input_panel.setStyleSheet("background: #f8f9fa; border-top: 1px solid #e9ecef;")
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(20, 15, 20, 15)
        
        self.input_field = QTextEdit()
        self.input_field.setPlaceholderText("Введите сообщение... (Ctrl+Enter для отправки)")
        self.input_field.setStyleSheet("""
            QTextEdit {
                background: white; border: 1px solid #ced4da; border-radius: 8px;
                padding: 12px; font-size: 14px;
            }
            QTextEdit:focus { border: 2px solid #667eea; }
        """)
        
        send_panel = QHBoxLayout()
        
        self.send_btn = QPushButton("Отправить")
        self.send_btn.setFixedHeight(45)
        self.send_btn.setMinimumWidth(120)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #667eea; color: white; border: none; border-radius: 8px;
                font-weight: 600; font-size: 14px;
            }
            QPushButton:hover { background: #5a6bc0; }
        """)
        self.send_btn.clicked.connect(self.send_message)
        
        send_panel.addStretch()
        send_panel.addWidget(self.send_btn)
        
        input_layout.addWidget(self.input_field, 1)
        input_layout.addLayout(send_panel)
        
        main_area_layout.addWidget(toolbar)
        main_area_layout.addWidget(self.chat_scroll, 1)
        main_area_layout.addWidget(input_panel)
        
        main_layout.addWidget(sidebar)
        main_layout.addWidget(main_area, 1)
        
        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self.send_message)
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self.new_conversation)
        
        # Load API key
        self.ai.api_key = self.db.get_setting("api_key")
    
    def new_conversation(self):
        title = "Новый диалог"
        self.current_conversation_id = self.db.create_conversation(title)
        # Сохраняем приветственное сообщение в базу для этого диалога
        welcome = "Добро пожаловать! Я ваш AI ассистент Danil."
        self.db.save_message(self.current_conversation_id, "assistant", welcome)
        # Кэшируем сообщения для этого диалога
        self.conversations[self.current_conversation_id] = [{"role": "assistant", "content": welcome}]
        # Очищаем экран и показываем приветствие
        self.clear_display()
        self.add_message(welcome, False)
        self.load_conversations()
        # Выделяем текущий диалог в списке
        self.select_current_conversation()
    
    def select_current_conversation(self):
        for i in range(self.conv_list.count()):
            item = self.conv_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self.current_conversation_id:
                self.conv_list.setCurrentItem(item)
                break
    
    def add_message(self, content, is_user=True):
        widget = QWidget()
        widget.setMinimumHeight(60)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 15, 20, 15)
        
        avatar = QLabel("👤" if is_user else "🤖")
        avatar.setStyleSheet("font-size: 20px;")
        
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: %s;
                border-radius: 12px;
                border: 1px solid %s;
            }
        """ % ("#f0f7ff" if is_user else "#f8f9fa", "#d0e3ff" if is_user else "#e9ecef"))
        
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(15, 12, 15, 12)
        
        name = QLabel("Вы" if is_user else "Danil AI")
        name.setStyleSheet("color: #2d7dff; font-weight: bold;" if is_user else "color: #444; font-weight: bold;")
        
        text = QLabel(content)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        frame_layout.addWidget(name)
        frame_layout.addWidget(text)
        
        layout.addWidget(avatar)
        layout.addWidget(frame, 1)
        
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, widget)
        QTimer.singleShot(50, self.scroll_to_bottom)
    
    def scroll_to_bottom(self):
        self.chat_scroll.verticalScrollBar().setValue(self.chat_scroll.verticalScrollBar().maximum())
    
    def clear_display(self):
        """Только очищает экран отображения (старый метод clear_screen)"""
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def clear_screen(self):
        """Очищает экран и удаляет все сообщения из текущего диалога"""
        if not self.current_conversation_id:
            return
        
        reply = QMessageBox.question(
            self, "Очистка диалога",
            "Вы уверены, что хотите очистить все сообщения в этом диалоге?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Удаляем сообщения из базы данных
            self.db.clear_conversation_messages(self.current_conversation_id)
            
            # Очищаем кэш сообщений
            if self.current_conversation_id in self.conversations:
                self.conversations[self.current_conversation_id] = []
            
            # Очищаем экран
            self.clear_display()
            
            # Добавляем новое приветственное сообщение
            welcome = "Диалог очищен. Я ваш AI ассистент Danil. Чем могу помочь?"
            self.db.save_message(self.current_conversation_id, "assistant", welcome)
            self.conversations[self.current_conversation_id].append({"role": "assistant", "content": welcome})
            self.add_message(welcome, False)
    
    def send_message(self):
        text = self.input_field.toPlainText().strip()
        if not text:
            return
        
        self.add_message(text, True)
        self.db.save_message(self.current_conversation_id, "user", text)
        # Добавляем в кэш
        if self.current_conversation_id not in self.conversations:
            self.conversations[self.current_conversation_id] = []
        self.conversations[self.current_conversation_id].append({"role": "user", "content": text})
        
        self.input_field.clear()
        
        # Показываем индикатор загрузки
        loading_widget = QWidget()
        loading_widget.setFixedHeight(60)
        loading_layout = QHBoxLayout(loading_widget)
        loading_layout.setContentsMargins(20, 15, 20, 15)
        
        avatar = QLabel("🤖")
        avatar.setStyleSheet("font-size: 20px;")
        
        frame = QFrame()
        frame.setStyleSheet("background: #f8f9fa; border-radius: 12px; border: 1px solid #e9ecef;")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(15, 12, 15, 12)
        
        name = QLabel("Danil AI")
        name.setStyleSheet("color: #444; font-weight: bold;")
        
        loading_text = QLabel("Генерация ответа...")
        
        frame_layout.addWidget(name)
        frame_layout.addWidget(loading_text)
        
        loading_layout.addWidget(avatar)
        loading_layout.addWidget(frame, 1)
        
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, loading_widget)
        self.scroll_to_bottom()
        
        # Генерируем ответ
        threading.Thread(target=self.generate_response, args=(text, loading_widget), daemon=True).start()
    
    def generate_response(self, user_message, loading_widget):
        # Получаем историю сообщений для текущего диалога из кэша
        messages = []
        if self.current_conversation_id in self.conversations:
            for msg in self.conversations[self.current_conversation_id]:
                if msg["role"] == "assistant" or msg["role"] == "user":
                    messages.append({"role": msg["role"], "content": msg["content"]})
        
        # Добавляем текущее сообщение пользователя
        messages.append({"role": "user", "content": user_message})
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        response = loop.run_until_complete(self.ai.generate_response(messages))
        loop.close()
        
        QMetaObject.invokeMethod(self, "update_chat",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, response),
            Q_ARG(object, loading_widget))
    
    @pyqtSlot(str, object)
    def update_chat(self, response, loading_widget):
        loading_widget.deleteLater()
        self.add_message(response, False)
        self.db.save_message(self.current_conversation_id, "assistant", response)
        # Добавляем в кэш
        if self.current_conversation_id not in self.conversations:
            self.conversations[self.current_conversation_id] = []
        self.conversations[self.current_conversation_id].append({"role": "assistant", "content": response})
    
    def switch_conversation(self, item):
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        self.current_conversation_id = conv_id
        
        # Очищаем экран
        self.clear_display()
        
        # Загружаем сообщения для этого диалога
        if conv_id not in self.conversations:
            # Если нет в кэше, загружаем из базы
            messages = self.db.get_conversation_history(conv_id)
            self.conversations[conv_id] = messages
        else:
            messages = self.conversations[conv_id]
        
        # Отображаем все сообщения
        for msg in messages:
            is_user = msg["role"] == "user"
            self.add_message(msg["content"], is_user)
    
    def load_conversations(self):
        self.conv_list.clear()
        conversations = self.db.get_all_conversations()
        for conv_id, title in conversations:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, conv_id)
            self.conv_list.addItem(item)
    
    def delete_conversation(self):
        if not self.current_conversation_id:
            return
        
        reply = QMessageBox.question(
            self, "Удаление диалога",
            "Вы уверены, что хотите удалить этот диалог?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Удаляем из базы
            self.db.delete_conversation(self.current_conversation_id)
            # Удаляем из кэша
            if self.current_conversation_id in self.conversations:
                del self.conversations[self.current_conversation_id]
            
            # Обновляем список диалогов
            self.load_conversations()
            
            # Проверяем, остались ли диалоги
            if self.conv_list.count() > 0:
                # Выбираем первый диалог из списка
                self.conv_list.setCurrentRow(0)
                self.switch_conversation(self.conv_list.item(0))
            else:
                # Если диалогов нет, очищаем экран и сбрасываем текущий ID
                self.current_conversation_id = None
                self.clear_display()
    
    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            # Проверяем валидность API ключа
            api_key = dialog.api_key.strip()
            if api_key and not self.ai.validate_api_key(api_key):
                QMessageBox.warning(
                    self,
                    "Неверный API ключ",
                    "Введите корректный API ключ (например, начинающийся с 'sk-') или оставьте поле пустым для использования локального режима."
                )
                return
            
            self.ai.api_key = api_key
            self.db.save_setting("api_key", api_key)

# ==================== SETTINGS DIALOG ====================
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setFixedSize(500, 350)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header = QWidget()
        header.setFixedHeight(70)
        header.setStyleSheet("background: #667eea;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        title = QLabel("Настройки")
        title.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        
        subtitle = QLabel("Настройте параметры вашего ассистента")
        subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.9); font-size: 13px;")
        
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        
        # Content
        content = QWidget()
        content.setStyleSheet("background: white;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(25, 25, 25, 25)
        content_layout.setSpacing(20)
        
        api_group = QGroupBox("API Настройки")
        api_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 15px; border: 1px solid #dee2e6;
                border-radius: 8px; margin-top: 12px; padding-top: 18px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 12px 0 12px;
            }
        """)
        
        api_layout = QVBoxLayout(api_group)
        api_layout.setSpacing(8)
        
        api_label = QLabel("OpenAI API Ключ:")
        api_label.setStyleSheet("color: #495057; font-weight: 500; font-size: 13px;")
        
        self.api_input = QLineEdit()
        self.api_input.setPlaceholderText("sk-...")
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_input.setMinimumHeight(40)
        self.api_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ced4da; border-radius: 6px; padding: 10px;
                font-size: 13px;
            }
            QLineEdit:focus { border: 2px solid #667eea; }
        """)
        
        api_note = QLabel("Оставьте пустым для использования локального режима")
        api_note.setStyleSheet("color: #6c757d; font-size: 12px; font-style: italic;")
        
        api_layout.addWidget(api_label)
        api_layout.addWidget(self.api_input)
        api_layout.addWidget(api_note)
        
        # Buttons
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 10, 0, 0)
        
        save_btn = QPushButton("Сохранить")
        save_btn.setFixedHeight(40)
        save_btn.setMinimumWidth(120)
        save_btn.setStyleSheet("""
            QPushButton {
                background: #667eea; color: white; border: none; border-radius: 8px;
                font-weight: 600; font-size: 13px;
            }
            QPushButton:hover { background: #5a6bc0; }
        """)
        save_btn.clicked.connect(self.accept)
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #6c757d; color: white; border: none; border-radius: 8px;
                font-weight: 600; font-size: 13px;
            }
            QPushButton:hover { background: #5a6268; }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(save_btn)
        button_layout.addSpacing(10)
        button_layout.addWidget(cancel_btn)
        
        content_layout.addWidget(api_group)
        content_layout.addStretch()
        content_layout.addWidget(button_widget)
        
        layout.addWidget(header)
        layout.addWidget(content, 1)
        
        # Load current settings
        if parent:
            self.api_input.setText(parent.ai.api_key)
    
    @property
    def api_key(self):
        return self.api_input.text().strip()

# ==================== MAIN ====================
def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = AIAssistant()
    window.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
