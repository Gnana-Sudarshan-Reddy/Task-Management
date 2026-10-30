import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import app as task_app


class TaskApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "tasks.db"
        self.database_patch = patch.object(task_app, "DATABASE_PATH", self.database_path)
        self.database_patch.start()
        task_app.initialize_database()

    def tearDown(self) -> None:
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def test_create_and_get_task(self) -> None:
        created = task_app.create_task(
            task_app.TaskCreate(title="  Write tests  ", description="  API checks  ")
        )

        self.assertGreater(created.id, 0)
        self.assertEqual(created.title, "Write tests")
        self.assertEqual(created.description, "API checks")
        self.assertFalse(created.completed)
        self.assertEqual(task_app.get_task(created.id), created)

    def test_list_tasks_filters_by_completion(self) -> None:
        pending = task_app.create_task(task_app.TaskCreate(title="Pending"))
        completed = task_app.create_task(task_app.TaskCreate(title="Completed"))
        task_app.update_task(completed.id, task_app.TaskUpdate(completed=True))

        self.assertEqual(
            [task.id for task in task_app.list_tasks(completed=False)], [pending.id]
        )
        self.assertEqual(
            [task.id for task in task_app.list_tasks(completed=True)], [completed.id]
        )
        self.assertEqual(len(task_app.list_tasks()), 2)

    def test_update_task_fields(self) -> None:
        created = task_app.create_task(task_app.TaskCreate(title="Original"))

        updated = task_app.update_task(
            created.id,
            task_app.TaskUpdate(title="  Revised  ", description="  Details  ", completed=True),
        )

        self.assertEqual(updated.title, "Revised")
        self.assertEqual(updated.description, "Details")
        self.assertTrue(updated.completed)

    def test_rejects_empty_update(self) -> None:
        created = task_app.create_task(task_app.TaskCreate(title="Task"))

        with self.assertRaises(HTTPException) as error:
            task_app.update_task(created.id, task_app.TaskUpdate())

        self.assertEqual(error.exception.status_code, 400)

    def test_rejects_blank_title(self) -> None:
        with self.assertRaises(HTTPException) as error:
            task_app.create_task(task_app.TaskCreate(title="   "))

        self.assertEqual(error.exception.status_code, 422)

    def test_create_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            task_app.TaskCreate.model_validate({"title": "Task", "unexpected": True})

    def test_missing_task_returns_not_found(self) -> None:
        with self.assertRaises(HTTPException) as error:
            task_app.get_task(999)

        self.assertEqual(error.exception.status_code, 404)

    def test_delete_task(self) -> None:
        created = task_app.create_task(task_app.TaskCreate(title="Remove"))

        task_app.delete_task(created.id)

        with self.assertRaises(HTTPException) as error:
            task_app.get_task(created.id)
        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
