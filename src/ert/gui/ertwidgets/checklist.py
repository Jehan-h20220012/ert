from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ert.gui.ertwidgets import SearchBox, addHelpToWidget, resourceIcon


class CheckList(QWidget):
    def __init__(self, model, label="", help_link="", custom_filter_button=None):
        """
        :param custom_filter_button:  if needed, add a button that opens a
        custom filter menu. Useful when search alone isn't enough to filter the
        list.
        :type custom_filter_button: QToolButton
        """
        QWidget.__init__(self)

        self._model = model

        if help_link != "":
            addHelpToWidget(self, help_link)

        layout = QVBoxLayout()

        self._createCheckButtons()

        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)

        self._search_box = SearchBox()

        check_button_layout = QHBoxLayout()

        check_button_layout.setContentsMargins(0, 0, 0, 0)
        check_button_layout.setSpacing(0)
        check_button_layout.addWidget(QLabel(label))
        check_button_layout.addStretch(1)
        check_button_layout.addWidget(self._checkAllButton)
        check_button_layout.addWidget(self._uncheckAllButton)

        layout.addLayout(check_button_layout)
        layout.addWidget(self._list)

        # Inserts the custom filter button, if provided. The caller is
        # responsible for all related actions.
        if custom_filter_button is not None:
            search_bar_layout = QHBoxLayout()
            search_bar_layout.addWidget(self._search_box)
            search_bar_layout.addWidget(custom_filter_button)
            layout.addLayout(search_bar_layout)
        else:
            layout.addWidget(self._search_box)

        self.setLayout(layout)

        self._checkAllButton.clicked.connect(self.checkAll)
        self._uncheckAllButton.clicked.connect(self.uncheckAll)
        self._list.itemChanged.connect(self.itemChanged)
        self._search_box.filterChanged.connect(self.filterList)
        self._list.customContextMenuRequested.connect(self.showContextMenu)

        self._model.selectionChanged.connect(self.modelChanged)
        self._model.modelChanged.connect(self.modelChanged)

        self.modelChanged()

    def _createCheckButtons(self):
        self._checkAllButton = QToolButton()
        self._checkAllButton.setIcon(resourceIcon("check.svg"))
        self._checkAllButton.setIconSize(QSize(16, 16))
        self._checkAllButton.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._checkAllButton.setAutoRaise(True)
        self._checkAllButton.setToolTip("Select all")
        self._uncheckAllButton = QToolButton()
        self._uncheckAllButton.setIcon(resourceIcon("checkbox_outline.svg"))
        self._uncheckAllButton.setIconSize(QSize(16, 16))
        self._uncheckAllButton.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._uncheckAllButton.setAutoRaise(True)
        self._uncheckAllButton.setToolTip("Unselect all")

    def itemChanged(self, item):
        """@type item: QListWidgetItem"""
        if item.checkState() == Qt.Checked:
            self._model.selectValue(str(item.text()))
        elif item.checkState() == Qt.Unchecked:
            self._model.unselectValue(str(item.text()))
        else:
            raise AssertionError("Unhandled checkstate!")

    def modelChanged(self):
        self._list.clear()

        items = self._model.getList()

        for item in items:
            list_item = QListWidgetItem(item)
            list_item.setFlags(list_item.flags() | Qt.ItemIsUserCheckable)

            if self._model.isValueSelected(item):
                list_item.setCheckState(Qt.Checked)
            else:
                list_item.setCheckState(Qt.Unchecked)

            self._list.addItem(list_item)

        self.filterList(self._search_box.filter())

    def setSelectionEnabled(self, enabled):
        self.setEnabled(enabled)
        self._checkAllButton.setEnabled(enabled)
        self._uncheckAllButton.setEnabled(enabled)

    def filterList(self, _filter):
        _filter = _filter.lower()

        for index in range(0, self._list.count()):
            item = self._list.item(index)
            text = str(item.text()).lower()

            if _filter == "":
                item.setHidden(False)
            elif _filter in text:
                item.setHidden(False)
            else:
                item.setHidden(True)

    def checkAll(self):
        """
        Checks all visible items in the list.
        """
        for index in range(0, self._list.count()):
            item = self._list.item(index)
            if not item.isHidden():
                self._model.selectValue(str(item.text()))

    def uncheckAll(self):
        """
        Unchecks all items in the list, visible or not
        """
        self._model.unselectAll()

    def checkSelected(self):
        items = []
        for item in self._list.selectedItems():
            items.append(str(item.text()))

        for item in items:
            self._model.selectValue(item)

    def uncheckSelected(self):
        items = []
        for item in self._list.selectedItems():
            items.append(str(item.text()))

        for item in items:
            self._model.unselectValue(item)

    def showContextMenu(self, point):
        p = self._list.mapToGlobal(point)
        menu = QMenu()
        check_selected = menu.addAction("Check selected")
        uncheck_selected = menu.addAction("Uncheck selected")
        menu.addSeparator()
        clear_selection = menu.addAction("Clear selection")

        selected_item = menu.exec_(p)

        if selected_item == check_selected:
            self.checkSelected()
        elif selected_item == uncheck_selected:
            self.uncheckSelected()
        elif selected_item == clear_selection:
            self._list.clearSelection()
