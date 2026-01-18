import sys
import os
import json
import uuid
from threading import Thread
from datetime import datetime

import requests
from urllib.parse import urljoin
import tempfile

import mysql.connector
from mysql.connector import Error

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QPushButton, QSlider, QLabel, QListView, QFileDialog,
                             QMessageBox, QStatusBar, QMenuBar, QAction, QSpacerItem,
                             QListWidget, QListWidgetItem, QLineEdit, QWidget,
                             QInputDialog, QDialog, QDialogButtonBox, QFormLayout,
                             QGroupBox, QGridLayout, QFrame, QTreeWidget, QTreeWidgetItem,
                             QProgressBar)

from PyQt5.QtCore import Qt, QUrl, QTimer, QBuffer, QIODevice
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent, QMediaPlaylist
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QIcon, QFont


class DatabaseManager:
    """Менеджер для работы с базой данных MySQL"""

    def __init__(self):
        self.connection = None
        self.config = {}
        self.load_db_config()
        self.connect()
        self.initialize_database()

    def load_db_config(self):
        """Загрузка конфигурации базы данных"""
        try:
            if os.path.exists('db_config.json'):
                with open('db_config.json', 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки конфигурации БД: {e}")
            # Конфигурация по умолчанию
            self.config = {
                'host': 'localhost',
                'port': 3306,
                'database': 'audio_player',
                'user': 'root',
                'password': 'root'
            }

    def save_db_config(self):
        """Сохранение конфигурации базы данных"""
        try:
            with open('db_config.json', 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения конфигурации БД: {e}")

    def connect(self):
        """Подключение к базе данных"""
        try:
            self.connection = mysql.connector.connect(
                host=self.config.get('host', 'localhost'),
                port=self.config.get('port', 3306),
                database=self.config.get('database', 'audio_player'),
                user=self.config.get('user', 'root'),
                password=self.config.get('password', 'root')
            )
            print("Подключение к БД успешно установлено")
            return True
        except Error as e:
            print(f"Ошибка подключения к БД: {e}")
            return False

    def initialize_database(self):
        """Инициализация базы данных (создание таблиц если они не существуют)"""
        if not self.connection:
            return

        try:
            cursor = self.connection.cursor()

            # Таблица для конфигурации сервера
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS server_config (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    config_key VARCHAR(100) UNIQUE NOT NULL,
                    config_value JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """)

            # Таблица категорий
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    category_id VARCHAR(50) UNIQUE NOT NULL,
                    parent_id VARCHAR(50),
                    name VARCHAR(255) NOT NULL,
                    icon VARCHAR(10) DEFAULT '📁',
                    data JSON NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_parent_id (parent_id),
                    INDEX idx_category_id (category_id)
                )
            """)

            # Таблица треков (опционально, можно хранить треки отдельно)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    track_id VARCHAR(50) UNIQUE NOT NULL,
                    category_id VARCHAR(50) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    path TEXT,
                    track_data JSON NOT NULL,
                    source_type ENUM('local', 'server') DEFAULT 'local',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_category_id (category_id),
                    INDEX idx_track_id (track_id)
                )
            """)

            self.connection.commit()
            cursor.close()
            print("База данных инициализирована")

        except Error as e:
            print(f"Ошибка инициализации БД: {e}")

    def save_server_config(self, key, value):
        """Сохранение конфигурации сервера в БД"""
        try:
            cursor = self.connection.cursor()
            sql = """
                INSERT INTO server_config (config_key, config_value) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE 
                config_value = %s,
                updated_at = CURRENT_TIMESTAMP
            """
            cursor.execute(sql, (key, json.dumps(value), json.dumps(value)))
            self.connection.commit()
            cursor.close()
            return True
        except Error as e:
            print(f"Ошибка сохранения конфигурации сервера: {e}")
            return False

    def load_server_config(self, key):
        """Загрузка конфигурации сервера из БД"""
        try:
            cursor = self.connection.cursor(dictionary=True)
            sql = "SELECT config_value FROM server_config WHERE config_key = %s"
            cursor.execute(sql, (key,))
            result = cursor.fetchone()
            cursor.close()

            if result and result['config_value']:
                return json.loads(result['config_value'])
            return None
        except Error as e:
            print(f"Ошибка загрузки конфигурации сервера: {e}")
            return None

    def save_categories(self, categories):
        """Сохранение всех категорий в БД (рекурсивно)"""
        try:
            cursor = self.connection.cursor()

            # Очищаем старые данные
            cursor.execute("DELETE FROM categories")

            # Сохраняем категории рекурсивно
            for category_id, category_data in categories.items():
                self._save_category_recursive(cursor, category_id, category_data, None)

            self.connection.commit()
            cursor.close()
            return True
        except Error as e:
            print(f"Ошибка сохранения категорий: {e}")
            return False

    def _save_category_recursive(self, cursor, category_id, category_data, parent_id):
        """Рекурсивное сохранение категории"""
        # Подготавливаем данные для сохранения
        data_to_save = {
            'tracks': category_data.get('tracks', []),
            'children': {}
        }

        sql = """
            INSERT INTO categories (category_id, parent_id, name, icon, data)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (
            category_id,
            parent_id,
            category_data['name'],
            category_data.get('icon', '📁'),
            json.dumps(data_to_save)
        ))

        # Сохраняем дочерние категории
        for child_id, child_data in category_data.get('children', {}).items():
            self._save_category_recursive(cursor, child_id, child_data, category_id)

    def load_categories(self):
        """Загрузка всех категорий из БД"""
        try:
            cursor = self.connection.cursor(dictionary=True)
            sql = "SELECT * FROM categories ORDER BY parent_id, category_id"
            cursor.execute(sql)
            rows = cursor.fetchall()
            cursor.close()

            if not rows:
                return None

            # Строим древовидную структуру
            categories = {}
            children_by_parent = {}

            # Сначала собираем все категории
            for row in rows:
                category_id = row['category_id']
                parent_id = row['parent_id']

                # Загружаем данные из JSON
                data = json.loads(row['data'])

                category = {
                    'name': row['name'],
                    'icon': row['icon'],
                    'tracks': data.get('tracks', []),
                    'children': {}
                }

                if parent_id is None:
                    # Корневая категория
                    categories[category_id] = category
                else:
                    # Запоминаем дочернюю категорию для последующего добавления
                    if parent_id not in children_by_parent:
                        children_by_parent[parent_id] = []
                    children_by_parent[parent_id].append((category_id, category))

            # Добавляем дочерние категории к родителям
            for parent_id, children in children_by_parent.items():
                # Ищем родительскую категорию
                parent_category = self._find_category_by_id(categories, parent_id)
                if parent_category:
                    for child_id, child_data in children:
                        parent_category['children'][child_id] = child_data

            return categories if categories else None

        except Error as e:
            print(f"Ошибка загрузки категорий: {e}")
            return None

    def _find_category_by_id(self, categories, target_id, current_path=None):
        """Рекурсивный поиск категории по ID"""
        if current_path is None:
            current_path = []

        for category_id, category_data in categories.items():
            if category_id == target_id:
                return category_data

            if category_data.get('children'):
                result = self._find_category_by_id(category_data['children'], target_id, current_path + [category_id])
                if result:
                    return result

        return None

    def save_tracks(self, category_id, tracks):
        """Сохранение треков для категории"""
        try:
            cursor = self.connection.cursor()

            # Удаляем старые треки для этой категории
            sql_delete = "DELETE FROM tracks WHERE category_id = %s"
            cursor.execute(sql_delete, (category_id,))

            # Добавляем новые треки
            sql_insert = """
                INSERT INTO tracks (track_id, category_id, name, path, track_data, source_type)
                VALUES (%s, %s, %s, %s, %s, %s)
            """

            for i, track in enumerate(tracks):
                track_id = f"{category_id}_track_{i}"

                if isinstance(track, dict):
                    name = track.get('name', f'Track {i}')
                    path = track.get('url', '')
                    source_type = 'server' if track.get('type') == 'server' else 'local'
                    track_data = track
                else:
                    name = os.path.basename(track)
                    path = track
                    source_type = 'local'
                    track_data = {'path': track, 'name': name}

                cursor.execute(sql_insert, (
                    track_id,
                    category_id,
                    name,
                    path,
                    json.dumps(track_data),
                    source_type
                ))

            self.connection.commit()
            cursor.close()
            return True

        except Error as e:
            print(f"Ошибка сохранения треков: {e}")
            return False

    def load_tracks(self, category_id):
        """Загрузка треков для категории"""
        try:
            cursor = self.connection.cursor(dictionary=True)
            sql = "SELECT track_data FROM tracks WHERE category_id = %s ORDER BY id"
            cursor.execute(sql, (category_id,))
            rows = cursor.fetchall()
            cursor.close()

            tracks = []
            for row in rows:
                if row['track_data']:
                    tracks.append(json.loads(row['track_data']))

            return tracks

        except Error as e:
            print(f"Ошибка загрузки треков: {e}")
            return []

    def close(self):
        """Закрытие соединения с БД"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("Соединение с БД закрыто")


class DBConfigDialog(QDialog):
    """Диалог настройки подключения к базе данных"""

    def __init__(self, parent=None, db_config=None):
        super().__init__(parent)
        self.db_config = db_config or {}
        self.setWindowTitle("Настройки базы данных")
        self.setMinimumWidth(400)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("localhost")
        self.host_edit.setText(self.db_config.get('host', 'localhost'))

        self.port_edit = QLineEdit()
        self.port_edit.setPlaceholderText("3306")
        self.port_edit.setText(str(self.db_config.get('port', 3306)))

        self.database_edit = QLineEdit()
        self.database_edit.setPlaceholderText("audio_player")
        self.database_edit.setText(self.db_config.get('database', 'audio_player'))

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("root")
        self.user_edit.setText(self.db_config.get('user', 'root'))

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("password")
        self.password_edit.setText(self.db_config.get('password', ''))
        self.password_edit.setEchoMode(QLineEdit.Password)

        form_layout.addRow("Хост:", self.host_edit)
        form_layout.addRow("Порт:", self.port_edit)
        form_layout.addRow("База данных:", self.database_edit)
        form_layout.addRow("Пользователь:", self.user_edit)
        form_layout.addRow("Пароль:", self.password_edit)

        layout.addLayout(form_layout)

        # Кнопка тестирования подключения
        self.test_button = QPushButton("Проверить подключение")
        self.test_button.clicked.connect(self.test_connection)
        layout.addWidget(self.test_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def test_connection(self):
        config = self.get_db_config()
        try:
            connection = mysql.connector.connect(
                host=config['host'],
                port=config['port'],
                database=config['database'],
                user=config['user'],
                password=config['password']
            )

            if connection.is_connected():
                QMessageBox.information(self, "Успех", "Подключение к базе данных успешно установлено!")
                connection.close()
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось подключиться к базе данных")

        except Error as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка подключения к базе данных:\n{str(e)}")

    def get_db_config(self):
        return {
            'host': self.host_edit.text().strip(),
            'port': int(self.port_edit.text() or 3306),
            'database': self.database_edit.text().strip(),
            'user': self.user_edit.text().strip(),
            'password': self.password_edit.text().strip()
        }


class ServerConfigDialog(QDialog):
    def __init__(self, parent=None, server_config=None):
        super().__init__(parent)
        self.server_config = server_config or {}
        self.setWindowTitle("Настройки сервера")
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #ffdb4d;
            }
            QLabel {
                color: #ffdb4d;
                font-weight: bold;
            }
            QLineEdit {
                background-color: #2d2d2d;
                color: #ffdb4d;
                border: 1px solid #404040;
                border-radius: 4px;
                padding: 6px 8px;
                font-weight: bold;
            }
            QPushButton {
                background-color: #404040;
                color: #ffdb4d;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #505050;
                color: #ffeb9e;
            }
            QPushButton:pressed {
                background-color: #606060;
                color: #ffcc00;
            }
        """)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        self.server_url_edit = QLineEdit()
        self.server_url_edit.setPlaceholderText("http://localhost:8000")
        if self.server_config:
            self.server_url_edit.setText(self.server_config.get('url', ''))

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Имя пользователя (если требуется)")
        if self.server_config:
            self.username_edit.setText(self.server_config.get('username', ''))

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Пароль (если требуется)")
        self.password_edit.setEchoMode(QLineEdit.Password)
        if self.server_config:
            self.password_edit.setText(self.server_config.get('password', ''))

        self.timeout_edit = QLineEdit()
        self.timeout_edit.setPlaceholderText("30")
        if self.server_config:
            self.timeout_edit.setText(str(self.server_config.get('timeout', 30)))
        else:
            self.timeout_edit.setText("30")

        form_layout.addRow("URL сервера:", self.server_url_edit)
        form_layout.addRow("Имя пользователя:", self.username_edit)
        form_layout.addRow("Пароль:", self.password_edit)
        form_layout.addRow("Таймаут (сек):", self.timeout_edit)

        layout.addLayout(form_layout)

        self.test_button = QPushButton("Проверить соединение")
        self.test_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.test_button.clicked.connect(self.test_connection)
        layout.addWidget(self.test_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def test_connection(self):
        url = self.server_url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Введите URL сервера")
            return

        try:
            test_url = urljoin(url, "/api/status")
            response = requests.get(test_url, timeout=10)
            if response.status_code == 200:
                QMessageBox.information(self, "Успех", "Соединение с сервером установлено!")
            else:
                QMessageBox.warning(self, "Ошибка", f"Сервер ответил с кодом: {response.status_code}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось подключиться к серверу:\n{str(e)}")

    def get_server_config(self):
        return {
            'url': self.server_url_edit.text().strip(),
            'username': self.username_edit.text().strip(),
            'password': self.password_edit.text().strip(),
            'timeout': int(self.timeout_edit.text() or 30)
        }


class CategoryDialog(QDialog):
    def __init__(self, parent=None, category_data=None, is_root_category=False):
        super().__init__(parent)
        self.category_data = category_data
        self.is_root_category = is_root_category
        self.setWindowTitle("Редактировать категорию" if category_data else "Добавить категорию")
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #ffdb4d;
            }
            QLabel {
                color: #ffdb4d;
                font-weight: bold;
            }
            QLineEdit {
                background-color: #2d2d2d;
                color: #ffdb4d;
                border: 1px solid #404040;
                border-radius: 4px;
                padding: 6px 8px;
                font-weight: bold;
            }
            QPushButton {
                background-color: #404040;
                color: #ffdb4d;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #505050;
                color: #ffeb9e;
            }
            QPushButton:pressed {
                background-color: #606060;
                color: #ffcc00;
            }
        """)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        self.name_edit = QLineEdit()
        self.icon_edit = QLineEdit()

        if self.category_data:
            self.name_edit.setText(self.category_data['name'])
            self.icon_edit.setText(self.category_data.get('icon', '📁'))

        form_layout.addRow("Название:", self.name_edit)
        form_layout.addRow("Иконка:", self.icon_edit)

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_category_data(self):
        return {
            'name': self.name_edit.text(),
            'icon': self.icon_edit.text() or '📁',
            'tracks': self.category_data['tracks'] if self.category_data else [],
            'children': self.category_data['children'] if self.category_data else {}
        }


class AudioPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.categories = {}
        self.current_category = None
        self.current_category_path = []
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)
        self.is_playing = False
        self.is_shuffle = False
        self.is_repeat = False
        self.current_playlist = []
        self.server_config = {}
        self.is_online_mode = False
        self.buffered_tracks = {}
        self.current_stream_buffer = None
        self.current_stream_file = None

        # Инициализация менеджера БД
        self.db_manager = DatabaseManager()
        if not self.db_manager.connection:
            QMessageBox.warning(self, "Ошибка", "Не удалось подключиться к базе данных!")

        self.setup_ui()
        self.setup_player()
        self.setup_connections()
        self.load_settings()
        self.load_categories()

    def setup_ui(self):
        self.setWindowTitle("Аудиоплеер - Локальный режим")
        self.setGeometry(100, 100, 1200, 800)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
                color: #ffdb4d;
            }
            QListView, QListWidget, QTreeWidget {
                background-color: #2d2d2d;
                color: #e0e0e0;
                border: none;
                outline: none;
            }
            QTreeWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3d3d3d;
            }
            QTreeWidget::item:selected {
                background-color: #404040;
                color: #ffdb4d;
            }
            QListView::item, QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #3d3d3d;
            }
            QListView::item:selected, QListWidget::item:selected {
                background-color: #404040;
                color: #ffdb4d;
            }
            QLineEdit {
                background-color: #3d3d3d;
                color: #ffdb4d;
                border: 1px solid #404040;
                border-radius: 15px;
                padding: 8px 12px;
                font-weight: bold;
            }
            QSlider::groove:horizontal {
                background: #404040;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffdb4d;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
            QSlider::sub-page:horizontal {
                background: #ffdb4d;
                border-radius: 3px;
            }
            QLabel {
                color: #ffdb4d;
                font-weight: bold;
            }
            QMenuBar {
                background-color: #2d2d2d;
                color: #ffdb4d;
            }
            QMenuBar::item:selected {
                background-color: #404040;
            }
            QMenu {
                background-color: #2d2d2d;
                color: #ffdb4d;
                border: 1px solid #404040;
            }
            QMenu::item:selected {
                background-color: #404040;
            }
            QStatusBar {
                background-color: #2d2d2d;
                color: #ffdb4d;
            }
            QGroupBox {
                color: #ffdb4d;
                font-weight: bold;
                border: 1px solid #404040;
                border-radius: 4px;
                margin-top: 10px;
            }
            QProgressBar {
                border: 1px solid #404040;
                border-radius: 4px;
                text-align: center;
                color: #ffdb4d;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #ffdb4d;
                border-radius: 3px;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        self.setup_sidebar(main_layout)
        self.setup_content_area(main_layout)
        self.create_menu()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.mode_indicator = QLabel("🔴 Локальный режим")
        self.mode_indicator.setStyleSheet("color: #ff6b6b; font-weight: bold; padding: 2px 8px;")
        self.status_bar.addPermanentWidget(self.mode_indicator)

        self.buffer_progress = QProgressBar()
        self.buffer_progress.setMaximumWidth(150)
        self.buffer_progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.buffer_progress)

        self.status_bar.showMessage("Готов к воспроизведению")

    def setup_sidebar(self, main_layout):
        sidebar_widget = QWidget()
        sidebar_widget.setMinimumWidth(300)
        sidebar_widget.setMaximumWidth(350)
        sidebar_widget.setStyleSheet("background-color: #2d2d2d;")

        sidebar_layout = QVBoxLayout(sidebar_widget)

        # Панель управления базой данных
        db_group = QGroupBox("База данных")
        db_layout = QVBoxLayout(db_group)

        db_buttons_layout = QHBoxLayout()
        self.db_config_button = QPushButton("⚙️ БД")
        self.db_config_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)

        self.db_test_button = QPushButton("📊 Статус")
        self.db_test_button.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
            }
        """)

        db_buttons_layout.addWidget(self.db_config_button)
        db_buttons_layout.addWidget(self.db_test_button)
        db_layout.addLayout(db_buttons_layout)

        sidebar_layout.addWidget(db_group)

        # Панель управления сервером
        server_group = QGroupBox("Сервер")
        server_layout = QVBoxLayout(server_group)

        server_buttons_layout = QHBoxLayout()
        self.server_config_button = QPushButton("⚙️ Сервер")
        self.server_config_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        self.sync_button = QPushButton("🔄 Синхр.")
        self.sync_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)

        server_buttons_layout.addWidget(self.server_config_button)
        server_buttons_layout.addWidget(self.sync_button)
        server_layout.addLayout(server_buttons_layout)

        sidebar_layout.addWidget(server_group)

        self.search_line_edit = QLineEdit()
        self.search_line_edit.setPlaceholderText("Поиск треков...")
        sidebar_layout.addWidget(self.search_line_edit)

        categories_group = QGroupBox("Структура категорий")
        categories_layout = QVBoxLayout(categories_group)

        self.categories_tree = QTreeWidget()
        self.categories_tree.setHeaderLabel("Категории")
        self.categories_tree.setStyleSheet("""
            QTreeWidget::item {
                height: 30px;
            }
            QTreeWidget::item:has-children {
                font-weight: bold;
            }
        """)
        categories_layout.addWidget(self.categories_tree)

        category_buttons_layout = QHBoxLayout()

        self.add_root_category_button = QPushButton("+ Корень")
        self.add_root_category_button.setStyleSheet("""
            QPushButton {
                background-color: #ff6b6b;
                color: #1a1a1a;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff8e8e;
                color: #1a1a1a;
            }
            QPushButton:pressed {
                background-color: #ff4d4d;
                color: #1a1a1a;
            }
        """)

        self.add_category_button = QPushButton("+ Подкат.")
        self.add_category_button.setStyleSheet("""
            QPushButton {
                background-color: #ffdb4d;
                color: #1a1a1a;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ffeb9e;
                color: #1a1a1a;
            }
            QPushButton:pressed {
                background-color: #ffcc00;
                color: #1a1a1a;
            }
        """)

        self.edit_category_button = QPushButton("✏️")
        self.edit_category_button.setStyleSheet("""
            QPushButton {
                background-color: #404040;
                color: #ffdb4d;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #505050;
                color: #ffeb9e;
            }
            QPushButton:pressed {
                background-color: #606060;
                color: #ffcc00;
            }
        """)

        self.delete_category_button = QPushButton("🗑️")
        self.delete_category_button.setStyleSheet("""
            QPushButton {
                background-color: #404040;
                color: #ff6b6b;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #505050;
                color: #ff8e8e;
            }
            QPushButton:pressed {
                background-color: #606060;
                color: #ff4d4d;
            }
        """)

        category_buttons_layout.addWidget(self.add_root_category_button)
        category_buttons_layout.addWidget(self.add_category_button)
        category_buttons_layout.addWidget(self.edit_category_button)
        category_buttons_layout.addWidget(self.delete_category_button)
        categories_layout.addLayout(category_buttons_layout)

        sidebar_layout.addWidget(categories_group)
        main_layout.addWidget(sidebar_widget)

    def setup_content_area(self, main_layout):
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)

        self.breadcrumb_layout = QHBoxLayout()
        self.breadcrumb_layout.addWidget(QLabel("Путь:"))
        self.update_breadcrumbs()
        content_layout.addLayout(self.breadcrumb_layout)

        self.current_section_label = QLabel("Выберите категорию")
        self.current_section_label.setStyleSheet("font-size: 24px; font-weight: bold; margin: 10px 0; color: #ffdb4d;")
        content_layout.addWidget(self.current_section_label)

        self.category_stats_label = QLabel("Треков: 0 | Подкатегорий: 0")
        self.category_stats_label.setStyleSheet("font-size: 14px; color: #a0a0a0; margin-bottom: 15px;")
        content_layout.addWidget(self.category_stats_label)

        self.tracks_label = QLabel("Треки:")
        self.tracks_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px 0; color: #ffdb4d;")
        content_layout.addWidget(self.tracks_label)

        self.content_list_view = QListView()
        self.content_model = QStandardItemModel()
        self.content_list_view.setModel(self.content_model)
        self.content_list_view.setStyleSheet("""
            QListView::item {
                padding: 10px;
                border-bottom: 1px solid #3d3d3d;
                color: #e0e0e0;
                font-size: 13px;
            }
            QListView::item:selected {
                background-color: #404040;
                color: #ffdb4d;
            }
        """)
        content_layout.addWidget(self.content_list_view, 1)

        self.setup_player_controls(content_layout)
        main_layout.addWidget(content_widget, 1)

    def setup_player_controls(self, content_layout):
        self.current_track_label = QLabel("Не выбран")
        self.current_track_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffdb4d; margin: 10px 0;")
        self.current_track_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(self.current_track_label)

        self.track_source_label = QLabel("")
        self.track_source_label.setStyleSheet("font-size: 12px; color: #a0a0a0; margin-bottom: 10px;")
        self.track_source_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(self.track_source_label)

        progress_layout = QHBoxLayout()
        self.current_time_label = QLabel("00:00")
        self.current_time_label.setStyleSheet("color: #ffdb4d; font-weight: bold; font-size: 12px; min-width: 40px;")
        self.progress_slider = QSlider(Qt.Horizontal)
        self.total_time_label = QLabel("00:00")
        self.total_time_label.setStyleSheet("color: #ffdb4d; font-weight: bold; font-size: 12px; min-width: 40px;")
        progress_layout.addWidget(self.current_time_label)
        progress_layout.addWidget(self.progress_slider)
        progress_layout.addWidget(self.total_time_label)
        content_layout.addLayout(progress_layout)

        volume_layout = QHBoxLayout()
        self.volume_icon_label = QLabel("🔊")
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(50)
        self.volume_label = QLabel("50%")
        volume_layout.addWidget(self.volume_icon_label)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_label)
        content_layout.addLayout(volume_layout)

        control_layout = QHBoxLayout()
        control_layout.addItem(QSpacerItem(40, 20))

        control_button_style = """
            QPushButton {
                background-color: #404040;
                color: #ffdb4d;
                border: none;
                border-radius: 25px;
                font-size: 16px;
                min-width: 50px;
                min-height: 50px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #505050;
                color: #ffeb9e;
            }
            QPushButton:pressed {
                background-color: #606060;
                color: #ffcc00;
            }
        """

        self.previous_button = QPushButton("⏮")
        self.previous_button.setStyleSheet(control_button_style)

        self.play_button = QPushButton("▶")
        self.play_button.setStyleSheet("""
            QPushButton {
                background-color: #ffdb4d;
                color: #1a1a1a;
                border: none;
                border-radius: 30px;
                font-size: 18px;
                min-width: 60px;
                min-height: 60px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ffeb9e;
                color: #1a1a1a;
            }
            QPushButton:pressed {
                background-color: #ffcc00;
                color: #1a1a1a;
            }
        """)

        self.pause_button = QPushButton("⏸")
        self.pause_button.setStyleSheet(control_button_style)

        self.stop_button = QPushButton("⏹")
        self.stop_button.setStyleSheet(control_button_style)

        self.next_button = QPushButton("⏭")
        self.next_button.setStyleSheet(control_button_style)

        self.shuffle_button = QPushButton("🔀")
        self.shuffle_button.setCheckable(True)
        self.shuffle_button.setStyleSheet("""
            QPushButton {
                background-color: #404040;
                color: #ffdb4d;
                border: none;
                border-radius: 15px;
                font-size: 14px;
                min-width: 30px;
                min-height: 30px;
            }
            QPushButton:checked {
                background-color: #ffdb4d;
                color: #1a1a1a;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)

        self.repeat_button = QPushButton("🔁")
        self.repeat_button.setCheckable(True)
        self.repeat_button.setStyleSheet("""
            QPushButton {
                background-color: #404040;
                color: #ffdb4d;
                border: none;
                border-radius: 15px;
                font-size: 14px;
                min-width: 30px;
                min-height: 30px;
            }
            QPushButton:checked {
                background-color: #ffdb4d;
                color: #1a1a1a;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)

        control_layout.addWidget(self.shuffle_button)
        control_layout.addWidget(self.previous_button)
        control_layout.addWidget(self.play_button)
        control_layout.addWidget(self.pause_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.next_button)
        control_layout.addWidget(self.repeat_button)
        control_layout.addItem(QSpacerItem(40, 20))
        content_layout.addLayout(control_layout)

        buttons_layout = QHBoxLayout()
        self.add_button = QPushButton("Добавить файлы")
        self.add_button.setStyleSheet("""
            QPushButton {
                background-color: #ffdb4d;
                color: #1a1a1a;
                border: none;
                padding: 10px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ffeb9e;
                color: #1a1a1a;
            }
            QPushButton:pressed {
                background-color: #ffcc00;
                color: #1a1a1a;
            }
        """)
        self.remove_button = QPushButton("Удалить")
        self.remove_button.setStyleSheet("""
            QPushButton {
                background-color: #404040;
                color: #ffdb4d;
                border: none;
                padding: 10px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #505050;
                color: #ffeb9e;
            }
            QPushButton:pressed {
                background-color: #606060;
                color: #ffcc00;
            }
        """)

        self.play_all_button = QPushButton("▶ Воспроизвести все")
        self.play_all_button.setStyleSheet("""
            QPushButton {
                background-color: #404040;
                color: #ffdb4d;
                border: none;
                padding: 10px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #505050;
                color: #ffeb9e;
            }
            QPushButton:pressed {
                background-color: #606060;
                color: #ffcc00;
            }
        """)

        buttons_layout.addWidget(self.add_button)
        buttons_layout.addWidget(self.remove_button)
        buttons_layout.addWidget(self.play_all_button)
        content_layout.addLayout(buttons_layout)

    def create_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("Файл")
        open_action = QAction("Открыть файлы...", self)
        open_action.triggered.connect(self.add_files)
        file_menu.addAction(open_action)

        open_folder_action = QAction("Открыть папку...", self)
        open_folder_action.triggered.connect(self.add_folder)
        file_menu.addAction(open_folder_action)

        file_menu.addSeparator()

        add_root_category_action = QAction("Добавить корневую категорию", self)
        add_root_category_action.triggered.connect(self.add_root_category)
        file_menu.addAction(add_root_category_action)

        file_menu.addSeparator()

        db_menu = menubar.addMenu("База данных")
        db_config_action = QAction("Настройки БД...", self)
        db_config_action.triggered.connect(self.configure_database)
        db_menu.addAction(db_config_action)

        db_test_action = QAction("Проверить подключение", self)
        db_test_action.triggered.connect(self.test_database_connection)
        db_menu.addAction(db_test_action)

        server_menu = menubar.addMenu("Сервер")
        server_config_action = QAction("Настройки сервера...", self)
        server_config_action.triggered.connect(self.configure_server)
        server_menu.addAction(server_config_action)

        sync_action = QAction("Синхронизировать с сервером", self)
        sync_action.triggered.connect(lambda: Thread(target=self.sync_with_server).start())
        server_menu.addAction(sync_action)

        toggle_mode_action = QAction("Переключить режим онлайн/оффлайн", self)
        toggle_mode_action.triggered.connect(self.toggle_online_mode)
        server_menu.addAction(toggle_mode_action)

        file_menu.addSeparator()
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        playback_menu = menubar.addMenu("Воспроизведение")
        play_action = QAction("Воспроизвести/Пауза", self)
        play_action.triggered.connect(self.toggle_play_pause)
        playback_menu.addAction(play_action)

        stop_action = QAction("Стоп", self)
        stop_action.triggered.connect(self.stop)
        playback_menu.addAction(stop_action)

        playback_menu.addSeparator()
        next_action = QAction("Следующий трек", self)
        next_action.triggered.connect(self.next)
        playback_menu.addAction(next_action)

        previous_action = QAction("Предыдущий трек", self)
        previous_action.triggered.connect(self.previous)
        playback_menu.addAction(previous_action)

    def setup_connections(self):
        self.categories_tree.itemClicked.connect(self.on_category_clicked)
        self.search_line_edit.textChanged.connect(self.on_search_text_changed)
        self.db_config_button.clicked.connect(self.configure_database)
        self.db_test_button.clicked.connect(self.test_database_connection)
        self.server_config_button.clicked.connect(self.configure_server)
        self.sync_button.clicked.connect(self.sync_with_server)
        self.add_root_category_button.clicked.connect(self.add_root_category)
        self.add_category_button.clicked.connect(self.add_category)
        self.edit_category_button.clicked.connect(self.edit_category)
        self.delete_category_button.clicked.connect(self.delete_category)
        self.add_button.clicked.connect(self.add_files)
        self.remove_button.clicked.connect(self.remove_track)
        self.play_all_button.clicked.connect(self.play_all_tracks)
        self.play_button.clicked.connect(self.play)
        self.pause_button.clicked.connect(self.pause)
        self.stop_button.clicked.connect(self.stop)
        self.next_button.clicked.connect(self.next)
        self.previous_button.clicked.connect(self.previous)
        self.shuffle_button.toggled.connect(self.toggle_shuffle)
        self.repeat_button.toggled.connect(self.toggle_repeat)
        self.progress_slider.sliderMoved.connect(self.set_position)
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.playlist.currentIndexChanged.connect(self.track_changed)
        self.content_list_view.doubleClicked.connect(self.play_double_clicked)
        self.player.stateChanged.connect(self.on_player_state_changed)

    def setup_player(self):
        self.player = QMediaPlayer()
        self.playlist = QMediaPlaylist()
        self.player.setPlaylist(self.playlist)
        self.current_track_index = -1
        self.player.setVolume(50)

    def load_settings(self):
        """Загрузка настроек сервера из БД"""
        if self.db_manager.connection:
            self.server_config = self.db_manager.load_server_config('server_config') or {}
            self.check_server_availability()

    def save_settings(self):
        """Сохранение настроек сервера в БД"""
        if self.db_manager.connection:
            self.db_manager.save_server_config('server_config', self.server_config)

    def check_server_availability(self):
        """Проверка доступности сервера"""
        if not self.server_config or not self.server_config.get('url'):
            self.is_online_mode = False
            return False

        try:
            test_url = urljoin(self.server_config['url'], "/api/status")
            response = requests.get(test_url, timeout=5)
            if response.status_code == 200:
                self.is_online_mode = True
                self.update_mode_indicator()
                return True
        except:
            self.is_online_mode = False

        self.update_mode_indicator()
        return False

    def update_mode_indicator(self):
        """Обновление индикатора режима работы"""
        if self.is_online_mode:
            self.mode_indicator.setText("🟢 Онлайн режим")
            self.mode_indicator.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 2px 8px;")
            self.setWindowTitle("Аудиоплеер - Онлайн режим")
        else:
            self.mode_indicator.setText("🔴 Локальный режим")
            self.mode_indicator.setStyleSheet("color: #ff6b6b; font-weight: bold; padding: 2px 8px;")
            self.setWindowTitle("Аудиоплеер - Локальный режим")

    def configure_database(self):
        """Настройка подключения к базе данных"""
        dialog = DBConfigDialog(self, self.db_manager.config)
        if dialog.exec_() == QDialog.Accepted:
            new_config = dialog.get_db_config()
            self.db_manager.config = new_config
            self.db_manager.save_db_config()

            # Переподключаемся с новыми настройками
            if self.db_manager.connect():
                QMessageBox.information(self, "Успех", "Подключение к базе данных успешно!")
                self.db_manager.initialize_database()
                self.load_categories()
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось подключиться к базе данных!")

    def test_database_connection(self):
        """Проверка подключения к базе данных"""
        if self.db_manager.connection and self.db_manager.connection.is_connected():
            QMessageBox.information(self, "Статус", "Соединение с базой данных активно!")
        else:
            QMessageBox.warning(self, "Ошибка", "Нет подключения к базе данных!")

    def toggle_online_mode(self):
        """Переключение между онлайн и оффлайн режимом"""
        if not self.server_config:
            QMessageBox.warning(self, "Ошибка", "Сначала настройте подключение к серверу!")
            return

        if self.is_online_mode:
            self.is_online_mode = False
        else:
            if self.check_server_availability():
                self.is_online_mode = True
            else:
                QMessageBox.warning(self, "Ошибка", "Сервер недоступен!")

        self.update_mode_indicator()

    def configure_server(self):
        """Настройка подключения к серверу"""
        dialog = ServerConfigDialog(self, self.server_config)
        if dialog.exec_() == QDialog.Accepted:
            new_config = dialog.get_server_config()
            self.server_config = new_config
            self.save_settings()
            self.check_server_availability()

    def sync_with_server(self):
        """Синхронизация с сервером"""
        if not self.server_config:
            QMessageBox.warning(self, "Ошибка", "Сначала настройте подключение к серверу!")
            return

        if not self.check_server_availability():
            QMessageBox.warning(self, "Ошибка", "Сервер недоступен!")
            return

        try:
            self.status_bar.showMessage("Синхронизация с сервером...")

            categories_url = urljoin(self.server_config['url'], "/user/playlist/player/")
            response = requests.get(categories_url, timeout=self.server_config.get('timeout', 30),
                                    json={"token": os.getenv("TOKEN")})

            if response.status_code == 200:
                server_categories = response.json()
                self.merge_categories(server_categories)
                self.update_categories_tree()
                self.save_categories_to_db()
                self.status_bar.showMessage("Синхронизация завершена успешно!")
            else:
                QMessageBox.warning(self, "Ошибка", f"Ошибка получения данных: {response.status_code}")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка синхронизации: {str(e)}")
            self.status_bar.showMessage("Ошибка синхронизации")

    def merge_categories(self, server_categories):
        """Объединение локальных и серверных категорий"""
        for category_id, category_data in server_categories.items():
            self.categories[category_id] = category_data
            self.mark_server_tracks(category_data)

    def mark_server_tracks(self, category_data):
        """Помечаем треки как серверные"""
        if 'tracks' in category_data:
            for i, track in enumerate(category_data['tracks']):
                if isinstance(track, str) and (track.startswith('http') or track.startswith('//')):
                    category_data['tracks'][i] = {
                        'url': track,
                        'type': 'server',
                        'name': os.path.basename(track)
                    }
                elif isinstance(track, dict) and track.get('type') == 'server':
                    continue
                elif isinstance(track, str) and os.path.exists(track):
                    continue
                else:
                    category_data['tracks'][i] = {
                        'url': track,
                        'type': 'server',
                        'name': os.path.basename(track) if isinstance(track, str) else 'Неизвестный трек'
                    }

        if 'children' in category_data:
            for child_data in category_data['children'].values():
                self.mark_server_tracks(child_data)

    def is_local_file(self, track_path):
        """Проверяет, является ли трек локальным файлом"""
        if isinstance(track_path, dict):
            return track_path.get('type') != 'server'
        return os.path.exists(track_path)

    def get_track_name(self, track_path):
        """Получает имя трека"""
        if isinstance(track_path, dict):
            return track_path.get('name', 'Неизвестный трек')
        return os.path.basename(track_path)

    def get_track_url(self, track_path):
        """Получает URL или путь к треку"""
        if isinstance(track_path, dict):
            return track_path.get('url', '')
        return track_path

    def load_categories(self):
        """Загрузка категорий из базы данных"""
        if self.db_manager.connection:
            categories = self.db_manager.load_categories()
            if categories:
                self.categories = categories
            else:
                self.categories = self.create_default_categories()
        else:
            self.categories = self.create_default_categories()

        self.update_categories_tree()
        if self.categories:
            first_category = next(iter(self.categories.keys()))
            self.switch_to_category(first_category)

    def create_default_categories(self):
        """Создает структуру категорий по умолчанию"""
        return {
            "main_library": {
                "name": "Моя музыка",
                "icon": "🎵",
                "tracks": [],
                "children": {
                    "favorites": {
                        "name": "Избранное",
                        "icon": "⭐",
                        "tracks": [],
                        "children": {}
                    },
                    "recent": {
                        "name": "Недавние",
                        "icon": "🕒",
                        "tracks": [],
                        "children": {}
                    }
                }
            }
        }

    def save_categories_to_db(self):
        """Сохранение категорий в базу данных"""
        if self.db_manager.connection:
            if self.db_manager.save_categories(self.categories):
                self.status_bar.showMessage("Категории сохранены в БД")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось сохранить категории в БД")

    def update_categories_tree(self):
        self.categories_tree.clear()
        for category_id, category_data in self.categories.items():
            self.build_tree_item(None, category_id, category_data)

    def build_tree_item(self, parent_item, category_id, category_data):
        item = QTreeWidgetItem([f"{category_data['icon']} {category_data['name']}"])
        item.setData(0, Qt.UserRole, category_id)

        if parent_item is None:
            self.categories_tree.addTopLevelItem(item)
        else:
            parent_item.addChild(item)

        for child_id, child_data in category_data.get('children', {}).items():
            self.build_tree_item(item, child_id, child_data)

        if category_data.get('children'):
            item.setExpanded(True)

    def get_category_by_path(self, path):
        """Получить категорию по пути"""
        if not path:
            return None

        current = self.categories
        for i, category_id in enumerate(path):
            if category_id in current:
                if i == len(path) - 1:
                    return current[category_id]
                else:
                    if 'children' in current[category_id]:
                        current = current[category_id]['children']
                    else:
                        return None
            else:
                return None
        return None

    def get_parent_category_by_path(self, path):
        """Получить родительскую категорию по пути"""
        if len(path) <= 1:
            return self.categories

        parent_path = path[:-1]
        current = self.categories
        for category_id in parent_path:
            if category_id in current and 'children' in current[category_id]:
                current = current[category_id]['children']
            else:
                return None
        return current

    def on_category_clicked(self, item):
        category_id = item.data(0, Qt.UserRole)
        self.switch_to_category(category_id)

    def switch_to_category(self, category_id):
        self.current_category = category_id

        if category_id in self.categories:
            self.current_category_path = [category_id]
        else:
            self.current_category_path = self.find_category_path(category_id)

        category_data = self.get_category_by_path(self.current_category_path)
        if category_data:
            self.current_section_label.setText(category_data['name'])
            self.update_breadcrumbs()
            self.update_category_display(category_data)
        else:
            if self.categories:
                first_category = next(iter(self.categories.keys()))
                self.switch_to_category(first_category)

    def find_category_path(self, category_id, current_path=None, current_node=None):
        """Рекурсивно найти путь к категории"""
        if current_path is None:
            current_path = []
        if current_node is None:
            current_node = self.categories

        for node_id, node_data in current_node.items():
            if node_id == category_id:
                return current_path + [node_id]

            if 'children' in node_data and node_data['children']:
                result = self.find_category_path(category_id, current_path + [node_id], node_data['children'])
                if result:
                    return result

        return []

    def update_breadcrumbs(self):
        for i in reversed(range(self.breadcrumb_layout.count())):
            widget = self.breadcrumb_layout.itemAt(i).widget()
            if widget and isinstance(widget, (QPushButton, QLabel)):
                widget.deleteLater()

        home_btn = QPushButton("🏠 Главная")
        home_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #ffdb4d;
                border: none;
                padding: 4px 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #ffeb9e;
                text-decoration: underline;
            }
        """)
        home_btn.clicked.connect(self.show_home)
        self.breadcrumb_layout.addWidget(home_btn)

        if self.current_category_path:
            self.breadcrumb_layout.addWidget(QLabel(">"))

        for i, category_id in enumerate(self.current_category_path):
            category_data = self.get_category_by_path(self.current_category_path[:i + 1])
            if category_data:
                btn = QPushButton(f"{category_data['icon']} {category_data['name']}")
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #ffdb4d;
                        border: none;
                        padding: 4px 8px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        color: #ffeb9e;
                        text-decoration: underline;
                    }
                """)
                btn.clicked.connect(
                    lambda checked, path=self.current_category_path[:i + 1]: self.navigate_to_path(path))
                self.breadcrumb_layout.addWidget(btn)

                if i < len(self.current_category_path) - 1:
                    separator = QLabel(">")
                    separator.setStyleSheet("color: #ffdb4d;")
                    self.breadcrumb_layout.addWidget(separator)

    def show_home(self):
        """Показать список всех корневых категорий"""
        self.current_category = None
        self.current_category_path = []
        self.current_section_label.setText("Все категории")
        self.category_stats_label.setText(f"Всего категорий: {len(self.categories)}")
        self.content_model.clear()

    def navigate_to_path(self, path):
        self.current_category_path = path
        self.current_category = path[-1]
        category_data = self.get_category_by_path(path)
        if category_data:
            self.switch_to_category(path[-1])

    def update_category_display(self, category_data):
        tracks_count = len(category_data.get('tracks', []))
        subcategories_count = len(category_data.get('children', {}))
        self.category_stats_label.setText(f"Треков: {tracks_count} | Подкатегорий: {subcategories_count}")
        self.display_tracks()

    def display_tracks(self):
        """Отображение треков с индикацией источника"""
        self.content_model.clear()
        category_data = self.get_category_by_path(self.current_category_path)
        if category_data:
            tracks = category_data.get('tracks', [])
            for i, track_path in enumerate(tracks):
                track_name = self.get_track_name(track_path)
                is_local = self.is_local_file(track_path)

                item_text = f"{i + 1}. {track_name}"
                if not is_local:
                    item_text += " 🌐"

                item = QStandardItem(item_text)
                item.setData(track_path, Qt.UserRole)

                if not is_local:
                    item.setForeground(Qt.green)

                self.content_model.appendRow(item)

    def add_root_category(self):
        dialog = CategoryDialog(self, is_root_category=True)
        if dialog.exec_() == QDialog.Accepted:
            category_data = dialog.get_category_data()
            if category_data['name']:
                category_id = str(uuid.uuid4())[:8]
                self.categories[category_id] = category_data

                self.update_categories_tree()
                self.save_categories_to_db()
                self.show_home()

                self.status_bar.showMessage(f"Корневая категория '{category_data['name']}' добавлена")

    def add_category(self):
        if not self.current_category:
            QMessageBox.warning(self, "Ошибка", "Выберите категорию для добавления подкатегории!")
            return

        current_category_data = self.get_category_by_path(self.current_category_path)
        if not current_category_data:
            QMessageBox.warning(self, "Ошибка", "Не удалось найти текущую категорию!")
            return

        dialog = CategoryDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            category_data = dialog.get_category_data()
            if category_data['name']:
                category_id = str(uuid.uuid4())[:8]

                if 'children' not in current_category_data:
                    current_category_data['children'] = {}
                current_category_data['children'][category_id] = category_data

                self.update_categories_tree()
                self.save_categories_to_db()
                self.update_category_display(current_category_data)

                self.status_bar.showMessage(f"Подкатегория '{category_data['name']}' добавлена")

    def edit_category(self):
        current_item = self.categories_tree.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Ошибка", "Выберите категорию для редактирования!")
            return

        category_id = current_item.data(0, Qt.UserRole)
        is_root_category = category_id in self.categories

        if is_root_category:
            category_data = self.categories[category_id]
        else:
            category_path = self.find_category_path(category_id)
            category_data = self.get_category_by_path(category_path)

        if category_data:
            dialog = CategoryDialog(self, category_data, is_root_category=is_root_category)
            if dialog.exec_() == QDialog.Accepted:
                new_data = dialog.get_category_data()
                category_data.update(new_data)
                self.update_categories_tree()
                self.save_categories_to_db()

                if category_id == self.current_category:
                    self.switch_to_category(category_id)

                self.status_bar.showMessage(f"Категория '{category_data['name']}' обновлена")

    def delete_category(self):
        current_item = self.categories_tree.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Ошибка", "Выберите категорию для удаления!")
            return

        category_id = current_item.data(0, Qt.UserRole)
        is_root_category = category_id in self.categories

        if is_root_category:
            category_data = self.categories[category_id]
            category_name = category_data['name']

            if len(self.categories) <= 1:
                QMessageBox.warning(self, "Ошибка", "Нельзя удалить последнюю корневую категорию!")
                return

            reply = QMessageBox.question(
                self, "Подтверждение",
                f"Удалить корневую категорию '{category_name}'?\n\n"
                f"Будет удалено: {len(category_data.get('tracks', []))} треков, "
                f"{len(category_data.get('children', {}))} подкатегорий"
            )

            if reply == QMessageBox.Yes:
                del self.categories[category_id]
                self.update_categories_tree()
                self.save_categories_to_db()
                self.show_home()
                self.status_bar.showMessage(f"Корневая категория '{category_name}' удалена")
        else:
            category_path = self.find_category_path(category_id)
            category_data = self.get_category_by_path(category_path)

            if not category_data:
                QMessageBox.warning(self, "Ошибка", "Категория не найдена!")
                return

            parent_data = self.get_parent_category_by_path(category_path)
            category_name = category_data['name']

            reply = QMessageBox.question(
                self, "Подтверждение",
                f"Удалить категорию '{category_name}'?\n\n"
                f"Будет удалено: {len(category_data.get('tracks', []))} треков, "
                f"{len(category_data.get('children', {}))} подкатегорий"
            )

            if reply == QMessageBox.Yes and parent_data:
                if category_id in parent_data:
                    del parent_data[category_id]
                    self.update_categories_tree()
                    self.save_categories_to_db()
                    if len(category_path) > 1:
                        self.switch_to_category(category_path[-2])
                    else:
                        self.show_home()
                    self.status_bar.showMessage(f"Категория '{category_name}' удалена")

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выберите аудиофайлы", "",
            "Аудио файлы (*.mp3 *.wav *.ogg *.flac *.m4a *.aac)"
        )

        if files and self.current_category:
            category_data = self.get_category_by_path(self.current_category_path)
            if category_data:
                added_count = 0
                for file_path in files:
                    if file_path not in category_data['tracks']:
                        category_data['tracks'].append(file_path)
                        added_count += 1

                self.display_tracks()
                self.save_categories_to_db()
                self.update_category_display(category_data)
                self.status_bar.showMessage(f"Добавлено {added_count} файлов")

    def add_folder(self):
        if not self.current_category:
            QMessageBox.warning(self, "Ошибка", "Выберите категорию для добавления файлов!")
            return

        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с музыкой")
        if folder and self.current_category:
            category_data = self.get_category_by_path(self.current_category_path)
            if category_data:
                added_count = 0
                audio_extensions = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}

                for root, dirs, files in os.walk(folder):
                    for file in files:
                        if os.path.splitext(file)[1].lower() in audio_extensions:
                            file_path = os.path.join(root, file)
                            if file_path not in category_data['tracks']:
                                category_data['tracks'].append(file_path)
                                added_count += 1

                self.display_tracks()
                self.save_categories_to_db()
                self.update_category_display(category_data)
                self.status_bar.showMessage(f"Добавлено {added_count} файлов из папки")

    def remove_track(self):
        if not self.current_category:
            QMessageBox.warning(self, "Ошибка", "Выберите категорию!")
            return

        current_index = self.content_list_view.currentIndex()
        if current_index.isValid():
            row = current_index.row()
            track_data = self.content_model.item(row).data(Qt.UserRole)

            category_data = self.get_category_by_path(self.current_category_path)
            if category_data and track_data in category_data['tracks']:
                category_data['tracks'].remove(track_data)

            self.display_tracks()
            self.save_categories_to_db()
            self.update_category_display(category_data)
            self.status_bar.showMessage("Трек удален")

    def on_search_text_changed(self, text):
        self.search_timer.start(300)

    def perform_search(self):
        if not self.current_category:
            return

        search_text = self.search_line_edit.text().lower()
        if not search_text:
            self.display_tracks()
            return

        self.content_model.clear()
        category_data = self.get_category_by_path(self.current_category_path)
        if category_data:
            tracks = category_data.get('tracks', [])
            for i, track_data in enumerate(tracks):
                track_name = self.get_track_name(track_data).lower()
                if search_text in track_name:
                    display_name = self.get_track_name(track_data)
                    is_local = self.is_local_file(track_data)

                    item_text = f"{i + 1}. {display_name}"
                    if not is_local:
                        item_text += " 🌐"

                    item = QStandardItem(item_text)
                    item.setData(track_data, Qt.UserRole)

                    if not is_local:
                        item.setForeground(Qt.green)

                    self.content_model.appendRow(item)

    def play_double_clicked(self, index):
        """Воспроизведение трека по двойному клику"""
        if not self.current_category:
            return

        track_data = self.content_model.item(index.row()).data(Qt.UserRole)
        self.play_track(track_data)

    def play_track(self, track_data):
        """Воспроизведение трека с поддержкой локальных и серверных файлов"""
        if self.is_local_file(track_data):
            track_path = self.get_track_url(track_data)
            if os.path.exists(track_path):
                self.play_local_track(track_path)
            else:
                QMessageBox.warning(self, "Ошибка", "Локальный файл не найден!")
        else:
            self.play_server_track(track_data)

    def play_local_track(self, track_path):
        """Воспроизведение локального трека"""
        self.playlist.clear()
        media_content = QMediaContent(QUrl.fromLocalFile(track_path))
        self.playlist.addMedia(media_content)

        category_data = self.get_category_by_path(self.current_category_path)
        if category_data:
            tracks = category_data.get('tracks', [])
            for track in tracks:
                if track != track_path and self.is_local_file(track):
                    local_path = self.get_track_url(track)
                    if os.path.exists(local_path):
                        self.playlist.addMedia(QMediaContent(QUrl.fromLocalFile(local_path)))

        self.player.play()
        self.is_playing = True
        self.track_source_label.setText("📁 Локальный файл")
        self.status_bar.showMessage(f"Воспроизведение: {os.path.basename(track_path)}")
        self.current_track_label.setText(os.path.basename(track_path))

    def play_server_track(self, track_data):
        """Воспроизведение серверного трека с буферизацией"""
        track_url = self.get_track_url(track_data)
        track_name = self.get_track_name(track_data)

        self.status_bar.showMessage(f"Буферизация: {track_name}...")
        self.buffer_progress.setVisible(True)
        self.buffer_progress.setValue(0)

        self.buffer_track_from_server(track_url, track_name)

    def buffer_track_from_server(self, track_url, track_name):
        """Буферизация трека с сервера"""
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            self.current_stream_file = temp_file.name
            temp_file.close()

            response = requests.get(track_url, stream=True, timeout=30)
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(self.current_stream_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            self.buffer_progress.setValue(progress)

                        QApplication.processEvents()

            self.playlist.clear()
            media_content = QMediaContent(QUrl.fromLocalFile(self.current_stream_file))
            self.playlist.addMedia(media_content)
            self.player.play()
            self.is_playing = True

            self.track_source_label.setText("🌐 Серверный поток")
            self.status_bar.showMessage(f"Воспроизведение: {track_name}")
            self.current_track_label.setText(track_name)
            self.buffer_progress.setVisible(False)

        except Exception as e:
            self.buffer_progress.setVisible(False)
            if self.current_stream_file and os.path.exists(self.current_stream_file):
                try:
                    os.unlink(self.current_stream_file)
                except:
                    pass
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки трека: {str(e)}")
            self.status_bar.showMessage("Ошибка загрузки трека")

    def play_all_tracks(self):
        """Воспроизведение всех треков в категории"""
        if not self.current_category:
            QMessageBox.warning(self, "Ошибка", "Выберите категорию!")
            return

        category_data = self.get_category_by_path(self.current_category_path)
        if category_data and category_data.get('tracks'):
            tracks = category_data['tracks']
            local_tracks = []

            for track in tracks:
                if self.is_local_file(track):
                    local_tracks.append(track)

            if local_tracks:
                self.playlist.clear()
                for track in local_tracks:
                    track_path = self.get_track_url(track)
                    if os.path.exists(track_path):
                        self.playlist.addMedia(QMediaContent(QUrl.fromLocalFile(track_path)))

                if self.playlist.mediaCount() > 0:
                    self.playlist.setCurrentIndex(0)
                    self.player.play()
                    self.is_playing = True
                    self.track_source_label.setText("📁 Локальные файлы")
                    self.status_bar.showMessage(f"Воспроизведение локальных треков ({len(local_tracks)} шт.)")
                    self.current_track_label.setText(self.get_track_name(local_tracks[0]))
            else:
                QMessageBox.information(self, "Информация", "В этой категории нет локальных треков для воспроизведения")

    def play(self):
        if self.player.state() != QMediaPlayer.PlayingState:
            if self.playlist.mediaCount() > 0:
                self.player.play()
                self.is_playing = True
                self.status_bar.showMessage("Воспроизведение")

    def pause(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.is_playing = False
            self.status_bar.showMessage("Пауза")

    def stop(self):
        self.player.stop()
        self.is_playing = False
        self.progress_slider.setValue(0)
        self.current_time_label.setText("00:00")
        self.status_bar.showMessage("Остановлено")

        if self.current_stream_file and os.path.exists(self.current_stream_file):
            try:
                os.unlink(self.current_stream_file)
            except:
                pass

    def toggle_play_pause(self):
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def next(self):
        if self.playlist.mediaCount() > 0:
            if self.is_shuffle:
                import random
                next_index = random.randint(0, self.playlist.mediaCount() - 1)
                self.playlist.setCurrentIndex(next_index)
            else:
                self.playlist.next()

            if self.player.state() != QMediaPlayer.PlayingState:
                self.player.play()
                self.is_playing = True

    def previous(self):
        if self.playlist.mediaCount() > 0:
            self.playlist.previous()
            if self.player.state() != QMediaPlayer.PlayingState:
                self.player.play()
                self.is_playing = True

    def toggle_shuffle(self, checked):
        self.is_shuffle = checked
        if checked:
            self.playlist.setPlaybackMode(QMediaPlaylist.Random)
            self.status_bar.showMessage("Режим перемешивания включен")
        else:
            self.playlist.setPlaybackMode(QMediaPlaylist.Sequential)
            self.status_bar.showMessage("Режим перемешивания выключен")

    def toggle_repeat(self, checked):
        self.is_repeat = checked
        if checked:
            self.playlist.setPlaybackMode(QMediaPlaylist.Loop)
            self.status_bar.showMessage("Режим повтора включен")
        else:
            if not self.is_shuffle:
                self.playlist.setPlaybackMode(QMediaPlaylist.Sequential)
            self.status_bar.showMessage("Режим повтора выключен")

    def set_volume(self, value):
        self.player.setVolume(value)
        self.volume_label.setText(f"{value}%")

        if value == 0:
            self.volume_icon_label.setText("🔇")
        elif value < 33:
            self.volume_icon_label.setText("🔈")
        elif value < 66:
            self.volume_icon_label.setText("🔉")
        else:
            self.volume_icon_label.setText("🔊")

    def set_position(self, position):
        self.player.setPosition(position)

    def position_changed(self, position):
        self.progress_slider.setValue(position)
        minutes = position // 60000
        seconds = (position % 60000) // 1000
        self.current_time_label.setText(f"{minutes:02d}:{seconds:02d}")

    def duration_changed(self, duration):
        self.progress_slider.setRange(0, duration)
        minutes = duration // 60000
        seconds = (duration % 60000) // 1000
        self.total_time_label.setText(f"{minutes:02d}:{seconds:02d}")

    def track_changed(self, index):
        if index >= 0 and self.playlist.mediaCount() > 0:
            media = self.playlist.media(index)
            url = media.canonicalUrl()
            if url.isLocalFile():
                track_name = os.path.basename(url.toLocalFile())
                self.status_bar.showMessage(f"Воспроизведение: {track_name}")
                self.current_track_label.setText(track_name)

    def on_player_state_changed(self, state):
        if state == QMediaPlayer.StoppedState:
            self.is_playing = False
            if (self.playlist.currentIndex() == self.playlist.mediaCount() - 1 and
                    self.is_repeat):
                self.playlist.setCurrentIndex(0)
                self.player.play()

            if self.current_stream_file and os.path.exists(self.current_stream_file):
                try:
                    os.unlink(self.current_stream_file)
                except:
                    pass

    def closeEvent(self, event):
        """Очистка при закрытии приложения"""
        if self.current_stream_file and os.path.exists(self.current_stream_file):
            try:
                os.unlink(self.current_stream_file)
            except:
                pass

        # Закрываем соединение с БД
        if self.db_manager:
            self.db_manager.close()

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    player = AudioPlayer()
    player.show()
    sys.exit(app.exec_())