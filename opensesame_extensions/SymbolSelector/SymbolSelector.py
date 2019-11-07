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
import ast
from libopensesame.oslogging import oslogger
from libqtopensesame.extensions import BaseExtension
from libqtopensesame.misc.translate import translation_context
_ = translation_context(u'SymbolSelector', category=u'extension')


class SymbolSelector(BaseExtension):

    def activate(self):

        mimetype = self.extension_manager.provide(u'ide_current_language')
        try:
            fnc = getattr(self, u'_get_{}_symbols'.format(mimetype))
        except AttributeError:
            oslogger.warning(u'don\'t know how to handle {}'.format(mimetype))
            return
        symbols = fnc(self.extension_manager.provide(u'ide_current_source'))
        haystack = []
        for name, lineno in symbols:
            haystack.append((name, lineno, self._jump_to_line))
        self.extension_manager.fire(
            u'quick_select',
            haystack=haystack,
            placeholder_text=_(u'Search symbols in current file …')
        )

    def _jump_to_line(self, lineno):

        self.extension_manager.fire('ide_jump_to_line', lineno=lineno)

    def _get_python_symbols(self, nodes):

        if isinstance(nodes, str):
            try:
                nodes = ast.parse(nodes).body
            except SyntaxError:
                self.extension_manager.fire(
                    u'notify',
                    message=_(u'Cannot parse symbols because of SyntaxError'),
                    category=u'warning'
                )
                return []
        symbols = []
        for node in nodes:
            if node.__class__.__name__ not in ('ClassDef', 'FunctionDef'):
                continue
            symbols.append((node.name, node.lineno))
            symbols += self._get_python_symbols(node.body)
        return symbols