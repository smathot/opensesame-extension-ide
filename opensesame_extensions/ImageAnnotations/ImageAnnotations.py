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
import uuid
import yaml
from qtpy import QtWidgets, QtCore
from pyqode.core import modes
from libopensesame.oslogging import oslogger
from libopensesame import misc
from libqtopensesame.misc.config import cfg
from libqtopensesame.extensions import BaseExtension
from libqtopensesame.misc.translate import translation_context
_ = translation_context(u'ImageAnnotations', category=u'extension')

CAPTURE_PLACEHOLDER = '# ... {} ... \n'.format(_('capturing'))
HOURGLASSES = ['# ○\n', '# ◔\n', '# ◑\n', '# ◕\n', '# ●\n']


class ImageAnnotations(BaseExtension):
    """Receives images that result from code execution (sent by JupyterConsole)
    and shows these as annotations next to the executed code. Relies on
    ImageAnnotationsMode and ImageAnnotationsPanel from pyqode.core.
    """
    
    def event_startup(self):
        """Creates a folder for the image files if it doesn't exist, and
        restores the image annotation info.
        """
        self._capturing = False
        self.enable_capture = False
        self._image_folder = os.path.join(
            self.main_window.home_folder,
            '.opensesame',
            'image_annotations'
        )
        if not os.path.exists(self._image_folder):
            oslogger.debug('creating {}'.format(self._image_folder))
            os.mkdir(self._image_folder)
        try:
            self._image_annotations = safe_yaml_load(cfg.image_annotations)
            assert(isinstance(self._image_annotations, dict))
        except BaseException:
            oslogger.warning('failed to parse image annotations from config')
            self._image_annotations = {}
        # Remove annotations for non-existing images and convert single
        # annotations to lists of annotations so that there can be multiple
        # annotations for the same code. The `list()` wrapping is necessary
        # so that we can modify the objects while iterating through them.
        for file_path, file_annotations in list(
            self._image_annotations.items()
        ):
            if not isinstance(file_annotations, dict):
                self._image_annotations[file_path] = {}
                continue
            for code, paths in list(file_annotations.items()):
                if isinstance(paths, basestring):
                    paths = [paths]
                paths = [path for path in paths if os.path.exists(path)]
                if paths:
                    file_annotations[code] = paths
                else:
                    del file_annotations[code]
                    
    def event_setting_changed(self, setting, value):
        """Toggles capture of output when this changed in the menu."""
        if setting != 'image_annotations_capture_output':
            return
        cfg.image_annotations_capture_output = value
        editor = self.extension_manager.provide('ide_current_editor')
        if editor is None:
            return
        try:
            mode = editor.modes.get('ImageAnnotationsMode')
        except KeyError:
            return
        self._set_annotations(editor, mode)
        
    def event_register_editor(self, editor):
        """When an editor is registered, an ImageAnnotationsMode is added, but
        only if the editor already has an ImageAnnotationsPanel, which is
        managed by pyqode_manager.
        """
        try:
            editor.panels.get('ImageAnnotationsPanel')
        except KeyError:
            return
        mode = modes.ImageAnnotationsMode()
        mode.annotation_clicked.connect(self._on_annotation_clicked)
        editor.modes.append(mode)
        self._set_annotations(editor, mode)
        
    def event_jupyter_execute_start(self):
        """Inserts a capture placeholder after the cursor when capturing is
        enabled.
        """
        if not cfg.image_annotations_capture_output:
            return
        if self._capturing:
            self.extension_manager.fire(
                'notify',
                message=_('Already capturing output')
            )
            return
        self._editor = self.extension_manager.provide('ide_current_editor')
        if self._editor is None:
            return
        self._capturing = True
        self._has_captured = False
        # The hourglass serves as a progress indicator, but also as a reference
        # to insert captured text before.
        self._hourglass = 0
        self._text_operation('\n' + HOURGLASSES[self._hourglass])
        QtCore.QTimer.singleShot(250, self._animate_hourglass)
        
    def _animate_hourglass(self):
        """Animates the hourglass."""
        if not self._capturing:
            self._text_operation(HOURGLASSES[self._hourglass], insert=False)
            return
        new_hourglass = (self._hourglass + 1) % len(HOURGLASSES)
        self._text_operation(
            HOURGLASSES[self._hourglass],
            insert=False,
            replace_by=HOURGLASSES[new_hourglass]
        )
        self._hourglass = new_hourglass
        QtCore.QTimer.singleShot(500, self._animate_hourglass)
    
    def event_jupyter_execute_finished(self):
        """Removes the capture placeholder when the Jupyter console is done
        executing.
        """
        self._capturing = False
        
    def event_jupyter_execute_result_text(self, text):
        """Gets text that is sent to the Jupyter console and captures it if
        capturing is enabled.
        """
        if not self._capturing:
            return
        # Ignore empty lines at the start
        if not self._has_captured and not text.strip():
            return
        self._has_captured = True
        self._text_operation(
            '\n'.join(
                ['# {}'.format(line) for line in text.splitlines()]
            ) + '\n',
            insert_position=self._editor.toPlainText().find(
                HOURGLASSES[self._hourglass]
                # CAPTURE_PLACEHOLDER
            )
        )
    
    def event_jupyter_execute_result_image(self, img, fmt, code):
        """Receives a new image annotation, where `img` is the image data,
        `fmt` is the format, and code is the code snippet that resulted in
        creating of the image.
        """
        editor = self.extension_manager.provide('ide_current_editor')
        if editor is None:
            return
        try:
            mode = editor.modes.get('ImageAnnotationsMode')
        except KeyError:
            return
        if editor.file.path not in self._image_annotations:
            self._image_annotations[editor.file.path] = {}
        if code not in self._image_annotations[editor.file.path]:
            self._image_annotations[editor.file.path][code] = []
        img_path = self._img_to_file(img, fmt)
        self._image_annotations[editor.file.path][code].append(img_path)
        if cfg.image_annotations_capture_output:
            md = '![]({})'.format(img_path)
            self._image_annotations[editor.file.path][md] = [img_path]
            self.event_jupyter_execute_result_text(md)
        self._set_annotations(editor, mode)
        
    def _set_annotations(self, editor, mode):
        """Sends the annotations to the AnnotationMode."""
        if cfg.image_annotations_capture_output:
            def annotation_filter(code): return code.startswith('![](')
        else:
            def annotation_filter(code): return not code.startswith('![](')
        cfg.image_annotations = yaml.dump(self._image_annotations)
        if editor.file.path in self._image_annotations:
            mode.set_annotations({
                editor.file.path: {
                    code: img_path
                    for (code, img_path)
                    in self._image_annotations[editor.file.path].items()
                    if annotation_filter(code)
                }
            })
        else:
            mode.set_annotations({})
        
    def _img_to_file(self, img, fmt):
        """Save an image to file and return the filename. Inspired by Spyder's
        `figurebrowser.py`.
        """
        if fmt == 'image/svg+xml':
            ext = '.svg'
        elif fmt == 'image/png':
            ext = '.png'
        elif fmt == 'image/jpeg':
            ext = '.jpg'
        else:
            raise ValueError('invalid image format: {}'.format(fmt))
        path = os.path.join(self._image_folder, uuid.uuid4().hex + ext)
        oslogger.debug('writing image to {}'.format(path))
        if fmt == 'image/svg+xml' and isinstance(img, str):
            img = img.encode('utf-8')
        with open(path, 'wb') as fd:
            fd.write(img)
        return path
    
    def _open_annotation(self, path):
        """Opens a single annotation image."""
        misc.open_url(path)
        
    def _open_folder(self):
        """Opens the folder that contains the image annotations."""
        misc.open_url(self._image_folder)
        
    def _clear_annotation(self, path=None):
        """Clear a single image annotation, or all image annotations in `path`
        is `None`.
        """
        editor = self.extension_manager.provide('ide_current_editor')
        if editor is None:
            return
        try:
            mode = editor.modes.get('ImageAnnotationsMode')
        except KeyError:
            return
        if path is None:
            self._image_annotations[editor.file.path] = {}
        else:
            for code, paths in list(
                self._image_annotations[editor.file.path].items()
            ):
                if path in paths:
                    paths.remove(path)
                # If there are still annotations remaining, update the paths to
                # the annotations, otherwise delete the entry for the code
                # alltogether
                if paths:
                    self._image_annotations[editor.file.path][code] = paths
                else:
                    del self._image_annotations[editor.file.path][code]
                # If no annotations remain for the file, remove the entry for
                # the file alltogether.
                if not self._image_annotations[editor.file.path]:
                    del self._image_annotations[editor.file.path]
        self._set_annotations(editor, mode)

    def _on_annotation_clicked(self, msg, event):
        """Shows a context menu on the annotation."""
        if event.button() != QtCore.Qt.RightButton:
            return
        menu = QtWidgets.QMenu(self.main_window)
        menu.addAction(_('Open'), lambda: self._open_annotation(msg.path))
        menu.addSeparator()
        menu.addAction(_('Clear'), lambda: self._clear_annotation(msg.path))
        menu.addAction(_('Clear all'), self._clear_annotation)
        menu.addSeparator()
        menu.addAction(_('Open folder'), self._open_folder)
        menu.exec(event.globalPos())

    def _text_operation(
        self,
        txt,
        insert=True,
        insert_position=None,
        replace_by=''
    ):
        """
        desc:
            Inserts or removes text while preserving the cursor position and
            selection.
        
        arguments:
            text
                The text to insert or remove.
            insert:
                False indicates that the first occurence of `text` should be
                removed.
            insert_position:
                Indicates the position of inserted text. If `None`, then the
                text is inserted at the next line below the current block.
            replace_by:
                Replaces the removed text by a string. Only applicable if
                `insert` is False.
        """
        # Get the cursor and remember the original position and anchor, where
        # the anchor is the start of the selection if any text is selected.
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        restore_selection = cursor.hasSelection()
        anchor = cursor.anchor()
        pos = cursor.position()
        if insert:
            if insert_position is None:
                # If no insert position is specified, we insert after the
                # selected text.
                cursor.setPosition(cursor.selectionEnd())
                insert_position = cursor.position()
            else:
                cursor.setPosition(insert_position)
            # Insert a newline if we're not already at the start of a line, so
            # that we don't append to existing lines.
            if not cursor.atBlockStart():
                txt = '\n' + txt
            cursor.insertText(txt)
            # If the original anchor and position were after the inserted text
            # then we need to move them forward.
            if insert_position < anchor:
                anchor += len(txt)
            if insert_position < pos:
                pos += len(txt)
        else:
            # Find the text, select it, and remove it.
            needle_pos = self._editor.toPlainText().find(txt)
            cursor.setPosition(needle_pos)
            cursor.movePosition(
                cursor.Right,
                cursor.KeepAnchor,
                len(txt)
            )
            cursor.removeSelectedText()
            if replace_by:
                cursor.insertText(replace_by)
            # If the original anchor and position were after the inserted text
            # then we need to move them backward.
            if needle_pos < anchor:
                anchor -= len(txt) - len(replace_by)
            if cursor.position() < pos:
                pos -= len(txt) - len(replace_by)
        # Restore the original anchor and position
        cursor.setPosition(anchor)
        if restore_selection:
            cursor.setPosition(pos, cursor.KeepAnchor)
        cursor.endEditBlock()
        self._editor.setTextCursor(cursor)