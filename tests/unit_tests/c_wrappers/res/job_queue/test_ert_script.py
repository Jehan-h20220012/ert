import pytest

from ert._c_wrappers.job_queue import ErtScript

from .workflow_common import WorkflowCommon


class ReturnErtScript(ErtScript):
    def run(self):
        return self.ert()


class AddScript(ErtScript):
    def run(self, arg1, arg2):
        return arg1 + arg2


class FailScript(ErtScript):
    def rum(self):
        pass


class NoneScript(ErtScript):
    def run(self, arg):
        assert arg is None


def test_ert_script_return_ert():
    script = ReturnErtScript("ert", storage=None)
    result = script.initializeAndRun([], [])
    assert result == "ert"


def test_ert_script_add():
    script = AddScript("ert", storage=None)

    result = script.initializeAndRun([int, int], ["5", "4"])

    assert result == 9

    with pytest.raises(ValueError):
        result = script.initializeAndRun([int, int], ["5", "4.6"])


def test_ert_script_failed_implementation():
    with pytest.raises(UserWarning):
        FailScript("ert", storage=None)


@pytest.mark.usefixtures("use_tmpdir")
def test_ert_script_from_file():
    WorkflowCommon.createErtScriptsJob()

    with open("syntax_error_script.py", "w", encoding="utf-8") as f:
        f.write("from ert._c_wrappers.enkf not_legal_syntax ErtScript\n")

    with open("import_error_script.py", "w", encoding="utf-8") as f:
        f.write("from ert._c_wrappers.enkf import DoesNotExist\n")

    with open("empty_script.py", "w", encoding="utf-8") as f:
        f.write("from ert._c_wrappers.enkf import ErtScript\n")

    script_object = ErtScript.loadScriptFromFile("subtract_script.py")

    script = script_object("ert", storage=None)
    result = script.initializeAndRun([int, int], ["1", "2"])
    assert result == -1

    with pytest.raises(ValueError):
        _ = ErtScript.loadScriptFromFile("syntax_error_script.py")
    with pytest.raises(ValueError):
        _ = ErtScript.loadScriptFromFile("import_error_script.py")
    with pytest.raises(ValueError):
        _ = ErtScript.loadScriptFromFile("empty_script.py")


def test_none_ert_script():
    # Check if None is not converted to string "None"
    script = NoneScript("ert", storage=None)

    script.initializeAndRun([str], [None])
