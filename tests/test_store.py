import pytest

from rdx.domain import Action
from rdx.engine import apply_actions, starter_project
from rdx.store import Conflict, Store


def test_revision_undo_redo_and_branch(tmp_path):
    store = Store(tmp_path / "test.sqlite")
    original = store.create(starter_project())
    changed = store.save(apply_actions(original, [Action(kind="project", params={"tempo":117})]), 0, "Tempo")
    assert changed.revision == 1
    with pytest.raises(Conflict):
        store.save(original, 0, "Stale")
    undone = store.move(original.id, 1, -1)
    assert undone.tempo == original.tempo and undone.revision == 2
    redone = store.move(original.id, 2, 1)
    assert redone.tempo == 117 and redone.revision == 3
    undone = store.move(original.id, 3, -1)
    branch = store.save(apply_actions(undone, [Action(kind="project", params={"tempo":135})]), 4, "New tempo")
    with pytest.raises(Conflict):
        store.move(branch.id, 5, 1)
    store.db.close()
    reopened = Store(tmp_path / "test.sqlite")
    assert reopened.get(branch.id) == branch
    reopened.db.close()
