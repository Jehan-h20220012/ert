from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ert._c_wrappers.enkf import EnkfVarType
from ert.gui.ertwidgets import addHelpToWidget, showWaitCursorWhileWaiting
from ert.gui.ertwidgets.caselist import CaseList
from ert.gui.ertwidgets.caseselector import CaseSelector
from ert.gui.ertwidgets.checklist import CheckList
from ert.gui.ertwidgets.models.selectable_list_model import SelectableListModel
from ert.libres_facade import LibresFacade


def createCheckLists(ert):
    parameter_model = SelectableListModel([])

    def getParameterList():
        return ert.ensembleConfig().getKeylistFromVarType(EnkfVarType.PARAMETER)

    parameter_model.getList = getParameterList
    parameter_check_list = CheckList(
        parameter_model, "Parameters", "init/select_parameters"
    )
    parameter_check_list.setMaximumWidth(300)

    members_model = SelectableListModel([])

    def getMemberList():
        return [str(member) for member in range(ert.getEnsembleSize())]

    members_model.getList = getMemberList
    member_check_list = CheckList(members_model, "Members", "init/select_members")
    member_check_list.setMaximumWidth(150)
    return (
        createRow(parameter_check_list, member_check_list),
        parameter_model,
        members_model,
    )


def createRow(*widgets):
    row = QHBoxLayout()

    for widget in widgets:
        row.addWidget(widget)

    row.addStretch()
    return row


class CaseInitializationConfigurationPanel(QTabWidget):
    @showWaitCursorWhileWaiting
    def __init__(self, ert, notifier):
        self.ert = ert
        self.notifier = notifier
        QTabWidget.__init__(self)
        self.setWindowTitle("Case management")
        self.setMinimumWidth(600)

        self.addCreateNewCaseTab()
        self.addInitializeFromScratchTab()
        self.addInitializeFromExistingTab()
        self.addShowCaseInfo()
        self.currentChanged.connect(self.on_tab_changed)

    @property
    def storage(self):
        return self.notifier.storage

    def addCreateNewCaseTab(self):
        panel = QWidget()
        panel.setObjectName("create_new_case_tab")
        layout = QVBoxLayout()
        case_list = CaseList(LibresFacade(self.ert), self.notifier)

        layout.addWidget(case_list, stretch=1)

        panel.setLayout(layout)

        self.addTab(panel, "Create new case")

    def addInitializeFromScratchTab(self):
        panel = QWidget()
        panel.setObjectName("initialize_from_scratch_panel")
        layout = QVBoxLayout()

        target_case = CaseSelector(self.notifier)
        row = createRow(QLabel("Target case:"), target_case)
        layout.addLayout(row)

        check_list_layout, parameter_model, members_model = createCheckLists(self.ert)
        layout.addLayout(check_list_layout)

        layout.addSpacing(10)

        initialize_button = QPushButton(
            "Initialize", objectName="initialize_from_scratch_button"
        )
        addHelpToWidget(initialize_button, "init/initialize_from_scratch")
        initialize_button.setMinimumWidth(75)
        initialize_button.setMaximumWidth(150)

        @showWaitCursorWhileWaiting
        def initializeFromScratch(_):
            parameters = parameter_model.getSelectedItems()
            target_ensemble = target_case.currentData()
            self.ert.sample_prior(
                ensemble=target_ensemble,
                active_realizations=[int(i) for i in members_model.getSelectedItems()],
                parameters=parameters,
            )

        initialize_button.clicked.connect(initializeFromScratch)
        layout.addWidget(initialize_button, 0, Qt.AlignCenter)

        layout.addSpacing(10)

        panel.setLayout(layout)
        self.addTab(panel, "Initialize from scratch")

    def addInitializeFromExistingTab(self):
        widget = QWidget()
        widget.setObjectName("intialize_from_existing_panel")
        layout = QVBoxLayout()

        target_case = CaseSelector(self.notifier)
        row = createRow(QLabel("Target case:"), target_case)
        layout.addLayout(row)

        source_case = CaseSelector(
            self.notifier,
            update_ert=False,
            show_only_initialized=True,
            ignore_current=True,
        )
        row = createRow(QLabel("Source case:"), source_case)
        layout.addLayout(row)

        row, _ = self.createTimeStepRow()
        layout.addLayout(row)

        layout.addSpacing(10)
        check_list_layout, parameter_model, members_model = createCheckLists(self.ert)
        layout.addLayout(check_list_layout)
        layout.addSpacing(10)

        initialize_button = QPushButton(
            "Initialize", objectName="initialize_existing_button"
        )
        if source_case.currentData() is None or target_case.currentData() is None:
            initialize_button.setEnabled(False)
        addHelpToWidget(initialize_button, "init/initialize_from_existing")
        initialize_button.setMinimumWidth(75)
        initialize_button.setMaximumWidth(150)

        @showWaitCursorWhileWaiting
        def initializeFromExisting(_):
            source_ensemble = source_case.currentData()
            target_ensemble = target_case.currentData()
            parameters = parameter_model.getSelectedItems()
            members = members_model.getSelectedItems()
            if source_ensemble.is_initalized:
                member_mask = [False] * self.ert.getEnsembleSize()
                for member in members:
                    member_mask[int(member)] = True
                source_ensemble.copy_from_case(target_ensemble, parameters, member_mask)

        initialize_button.clicked.connect(initializeFromExisting)
        layout.addWidget(initialize_button, 0, Qt.AlignCenter)

        layout.addSpacing(10)

        layout.addStretch()
        widget.setLayout(layout)
        self.addTab(widget, "Initialize from existing")

    def createTimeStepRow(self):
        history_length_spinner = QSpinBox()
        addHelpToWidget(history_length_spinner, "config/init/history_length")
        history_length_spinner.setMinimum(0)
        history_length_spinner.setMaximum(max(0, self.ert.getHistoryLength()))

        initial = QToolButton()
        initial.setText("Initial")
        addHelpToWidget(initial, "config/init/history_length")

        def setToMin():
            history_length_spinner.setValue(0)

        initial.clicked.connect(setToMin)

        end_of_time = QToolButton()
        end_of_time.setText("End of time")
        addHelpToWidget(end_of_time, "config/init/history_length")

        def setToMax():
            history_length_spinner.setValue(self.ert.getHistoryLength())

        end_of_time.clicked.connect(setToMax)

        row = createRow(
            QLabel("Timestep:"), history_length_spinner, initial, end_of_time
        )

        return row, history_length_spinner

    def addShowCaseInfo(self):
        case_widget = QWidget()
        layout = QVBoxLayout()

        case_selector = CaseSelector(
            self.notifier,
            update_ert=False,
            help_link="init/selected_case_info",
        )
        row1 = createRow(QLabel("Select case:"), case_selector)

        layout.addLayout(row1)

        self._case_info_area = QTextEdit(objectName="html_text")
        self._case_info_area.setReadOnly(True)
        self._case_info_area.setMinimumHeight(300)

        row2 = createRow(QLabel("Case info:"), self._case_info_area)

        layout.addLayout(row2)

        case_widget.setLayout(layout)

        self.show_case_info_case_selector = case_selector
        case_selector.currentIndexChanged[int].connect(self._showInfoForCase)
        self.notifier.ertChanged.connect(self._showInfoForCase)

        self.addTab(case_widget, "Case info")

    def _showInfoForCase(self, index=None):
        if index is None:
            if self.notifier.current_case is not None:
                states = self.notifier.current_case.state_map
            else:
                states = []
        else:
            ensemble = self.show_case_info_case_selector.itemData(index)
            if ensemble is not None:
                states = ensemble.state_map
            else:
                states = []

        html = "<table>"
        for state_index, value in enumerate(states):
            html += f"<tr><td width=30>{state_index:d}.</td><td>{value.name}</td></tr>"

        html += "</table>"

        self._case_info_area.setHtml(html)

    @showWaitCursorWhileWaiting
    def on_tab_changed(self, p_int):
        if self.tabText(p_int) == "Case info":
            self._showInfoForCase()
