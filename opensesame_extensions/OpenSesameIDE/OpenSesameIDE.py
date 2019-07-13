# coding=utf-8

"""
This file is part of OpenSesame.

OpenSesame is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

OpenSesame is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with OpenSesame.  If not, see <http://www.gnu.org/licenses/>.
"""

from libopensesame.py3compat import *
import os
import sys
import ast
import fnmatch
from libopensesame.oslogging import oslogger
from libqtopensesame.extensions import BaseExtension
from libqtopensesame.misc.config import cfg
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QFileDialog
from opensesame_ide import FolderBrowserDockWidget, MenuBar
from libqtopensesame.misc.translate import translation_context
from pyqode.core import widgets
from fallback_code_edit import FallbackCodeEdit
_ = translation_context(u'OpenSesameIDE', category=u'extension')


class OpenSesameIDE(BaseExtension):

    def event_startup(self):

        if u'--ide' not in sys.argv:
            return
        os.path.splitunc = lambda path: ('', path)  # Backwards compatibility
        self._patch_behavior()
        self._scetw = widgets.SplittableCodeEditTabWidget(self.main_window)
        self._scetw.fallback_editor = FallbackCodeEdit
        self._scetw.tab_name = u'OpenSesameIDE'
        self._add_ide_tab()
        self._dock_widgets = {}
        self._set_ignore_patterns()
        self._restore_open_folders()

    def open_document(self, path):

        editor = self._scetw.open_document(path)
        self.extension_manager.fire(
            u'register_editor',
            editor=editor
        )

    def remove_folder_browser_dock_widget(self, dock_widget):

        oslogger.info(u'removing folder browser: {}'.format(dock_widget.path))
        del self._dock_widgets[dock_widget.path]

    def close_tab(self):

        tab_widget = self._current_tabwidget()
        if tab_widget is not None:
            tab_widget.close()

    def close_all_tabs(self):

        tab_widget = self._current_tabwidget()
        if tab_widget is not None:
            tab_widget.close_all()

    def switch_tab_next(self):

        self._switch_tab(1)

    def switch_tab_previous(self):

        self._switch_tab(-1)

    def split_horizontal(self):

        self._split(Qt.Horizontal)

    def split_vertical(self):

        self._split(Qt.Vertical)

    def select_and_open_folder(self):

        path = QFileDialog.getExistingDirectory(self.main_window)
        if isinstance(path, tuple):
            path = path[0]
        if path:
            self._open_folder(path)
            self._remember_open_folders()

    def new_file(self):

        self._scetw.create_new_document()

    def save_file(self):

        self._scetw.save_current()

    def save_file_as(self):

        self._scetw.save_current_as()

    def open_file(self):

        path = QFileDialog.getOpenFileName(
            self.main_window,
            _(u"Open file"),
            directory=cfg.file_dialog_path
        )
        if isinstance(path, tuple):
            path = path[0]
        if not path:
            return
        self.open_document(path)

    def toggle_folder_browsers(self):

        hidden = any(
            not dockwidget.isVisible()
            for dockwidget in self._dock_widgets.values()
        )
        oslogger.info('setting folder-browser visibility to {}'.format(hidden))
        for dockwidget in self._dock_widgets.values():
            dockwidget.setVisible(hidden)

    def toggle_console(self):

        if not self._menubar._action_toggle_console.isChecked():
            self.main_window.ui.dock_stdout.setVisible(False)
            return
        self.main_window.ui.console.focus()
        self.main_window.ui.dock_stdout.setVisible(True)

    def quick_select_symbols(self):

        editor = self._scetw.current_widget()
        if not editor:
            return
        symbols = self._list_symbols(ast.parse(editor.toPlainText()).body)
        haystack = []
        for name, lineno in symbols:
            haystack.append((name, lineno, self._jump_to_line))
        self.extension_manager.fire(u'quick_select', haystack=haystack)

    def extension_filter(self, ext_name):

        return ext_name not in [
            u'notifications',
            u'plugin_manager',
            u'pyqode_manager',
            u'update_checker'
            u'bug_report',
            u'QuickSelector',
        ]

    def _jump_to_line(self, lineno):

        editor = self._scetw.current_widget()
        if not editor:
            return
        lines = editor.toPlainText().split(u'\n')
        position = sum([len(line) for line in lines[:lineno - 1]]) + lineno - 1
        cursor = editor.textCursor()
        cursor.setPosition(position)
        editor.setTextCursor(cursor)

    def _list_symbols(self, body):

        symbols = []
        for node in body:
            if node.__class__.__name__ not in ('ClassDef', 'FunctionDef'):
                continue
            symbols.append((node.name, node.lineno))
            symbols += self._list_symbols(node.body)
        return symbols

    def quick_select_files(self):

        haystack = []
        for dock_widget in self._dock_widgets.values():
            for path in self._list_files(dock_widget.path):
                label = u'{}\n{}'.format(
                    os.path.basename(path),
                    path[len(dock_widget.path) + 1:]
                )
                data = path
                haystack.append((label, data, self.open_document))
        self.extension_manager.fire(u'quick_select', haystack=haystack)

    def _list_files(self, dirname):

        files = []
        ignore_patterns = self.ignore_patterns
        gitignore = os.path.join(dirname, u'.gitignore')
        if os.path.exists(gitignore):
            oslogger.debug('excluding patterns from {}'.format(gitignore))
            with open(gitignore) as fd:
                ignore_patterns += [p.strip() for p in fd.read().split(u'\n')]
        ignore_patterns = [p for p in ignore_patterns if p]
        for basename in os.listdir(dirname):
            path = os.path.join(dirname, basename)
            if any(
                (
                    ignore_pattern in path or
                    fnmatch.fnmatch(basename, ignore_pattern)
                )
                for ignore_pattern in ignore_patterns
            ):
                continue
            if os.path.isdir(path):
                files += self._list_files(path)
            else:
                files.append(path)
        return files

    def _split(self, direction):

        editor = self._scetw.current_widget()
        if editor is None:
            return
        self._scetw.split(editor, direction)

    def _open_folder(self, path):

        if path in self._dock_widgets:
            return
        oslogger.info(u'adding folder browser: {}'.format(path))
        dock_widget = FolderBrowserDockWidget(self.main_window, self, path)
        self.main_window.addDockWidget(
            Qt.LeftDockWidgetArea,
            dock_widget
        )
        self._dock_widgets[path] = dock_widget

    def _patch_close_event(self, fnc):

        def inner(e):

            self._scetw.closeEvent(e)
            if e.isAccepted():
                fnc(e)

        return inner

    def _patch_behavior(self):

        # We open the IDE in a tab, and then set one-tab mode so that there
        # aren't two layers of tabs. When another tab (say preferences) is
        # opened, we disable one-tab mode, and then re-enable it again when
        # the IDE tab is the only tab,
        self.tabwidget.switch(u'OpenSesameIDE')
        if not self.main_window.ui.action_onetabmode.isChecked():
            self.main_window.ui.action_onetabmode.trigger()
        self.tabwidget.add = self._patch_tabwidget_add(self.tabwidget.add)
        self.tabwidget.tabCloseRequested.connect(self._on_tabwidget_close)
        self.tabwidget.shortcut_switch_left.setKey(u'')
        self.tabwidget.shortcut_switch_right.setKey(u'')
        # Create a custom menubar
        self._menubar = MenuBar(self.main_window, self)
        self.main_window.setMenuBar(self._menubar)
        # Patch the starting and closing of the app
        self.main_window.restore_window_state = \
            self._patch_restore_window_state(
                self.main_window.restore_window_state
            )
        self.main_window.closeEvent = self._patch_close_event(
            self.main_window.closeEvent
        )
        # PyQode needs a bit of patching to deal properly with keyboard
        # shortcuts
        self._patch_pyqode()

    def _patch_tabwidget_add(self, fnc):

        def inner(widget, *args, **kwargs):

            if (
                self.tabwidget.count() > 1 and
                self.main_window.ui.action_onetabmode.isChecked()
            ):
                self.main_window.ui.action_onetabmode.trigger()
            return fnc(widget, *args, **kwargs)

        return inner

    def _on_tabwidget_close(self, index):

        if self.tabwidget.get_widget(u'OpenSesameIDE') is None:
            self._add_ide_tab()
        if self.tabwidget.count() > 1:
            return
        if not self.main_window.ui.action_onetabmode.isChecked():
            self.main_window.ui.action_onetabmode.trigger()

    def _add_ide_tab(self):

        self.tabwidget.add(
            self._scetw,
            u'accessories-text-editor',
            'IDE'
        )

    def _patch_restore_window_state(self, fnc):

        def inner():

            fnc()
            self.main_window.ui.toolbar_main.hide()
            self.main_window.ui.toolbar_items.hide()
            self.main_window.ui.dock_stdout.show()
            self.main_window.ui.dock_overview.hide()
            self.main_window.ui.dock_pool.hide()
            try:
                self.extension_manager['variable_inspector'].set_visible(False)
            except Exception:
                pass

        return inner

    def _set_ignore_patterns(self):

        self.ignore_patterns = [
            p.strip()
            for p in cfg.opensesame_ide_ignore_patterns.split(u',')
        ]

    def _remember_open_folders(self):

        folders = [d.path for d in self._dock_widgets.values()]
        cfg.opensesame_ide_last_folder = u';'.join(folders)

    def _restore_open_folders(self):

        folders = [
            folder
            for folder in cfg.opensesame_ide_last_folder.split(u';')
            if os.path.isdir(folder)
        ]
        if not folders:
            folders = [os.getcwd()]
        for folder in folders:
            self._open_folder(folder)

    def _current_editor(self):

        return self._scetw.current_widget()

    def _current_tabwidget(self):

        editor = self._current_editor()
        if editor is None:
            return
        return editor.parent().parent()

    def _current_splitter(self):

        editor = self._current_editor()
        if editor is None:
            return self._scetw
        return editor.parent().parent().parent()

    def _switch_tab(self, direction):

        tabwidget = self._current_tabwidget()
        if tabwidget is None:
            return
        tabwidget.setCurrentIndex(
            (tabwidget.currentIndex() + direction) % tabwidget.count()
        )

    def _patch_pyqode_tab_bar_menu(self, fnc):

        def inner(self):

            fnc(self)
            self.a_close.setShortcut('')
            self.a_close_all.setShortcut('')

        return inner

    def _patch_pyqode(self):

        widgets.splittable_tab_widget.BaseTabWidget._create_tab_bar_menu = \
            self._patch_pyqode_tab_bar_menu(
                widgets.splittable_tab_widget.BaseTabWidget._create_tab_bar_menu
            )
