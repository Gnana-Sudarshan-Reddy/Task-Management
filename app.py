from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field


DATABASE_PATH = Path(__file__).with_name("tasks.db")


@contextmanager
def connect_database() -> Generator[sqlite3.Connection, None, None]:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with connect_database() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    completed: bool | None = None


class Task(BaseModel):
    id: int
    title: str
    description: str
    completed: bool
    created_at: str
    updated_at: str


def task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        completed=bool(row["completed"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Task Manager API", version="1.0.0", lifespan=lifespan)


@app.get("/api/tasks", response_model=list[Task])
def list_tasks(completed: bool | None = None) -> list[Task]:
    query = "SELECT * FROM tasks"
    parameters: tuple[int, ...] = ()
    if completed is not None:
        query += " WHERE completed = ?"
        parameters = (int(completed),)
    query += " ORDER BY created_at DESC, id DESC"
    with connect_database() as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [task_from_row(row) for row in rows]


@app.post("/api/tasks", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(task: TaskCreate) -> Task:
    title = task.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title cannot be blank.")
    now = datetime.now(timezone.utc).isoformat()
    with connect_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO tasks (title, description, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (title, task.description.strip(), now, now),
        )
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return task_from_row(row)


@app.get("/api/tasks/{task_id}", response_model=Task)
def get_task(task_id: int) -> Task:
    with connect_database() as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task_from_row(row)


@app.patch("/api/tasks/{task_id}", response_model=Task)
def update_task(task_id: int, updates: TaskUpdate) -> Task:
    changes = updates.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Provide at least one field to update.")
    if "title" in changes:
        if changes["title"] is None or not changes["title"].strip():
            raise HTTPException(status_code=422, detail="Title cannot be blank.")
        changes["title"] = changes["title"].strip()
    if "description" in changes and changes["description"] is None:
        raise HTTPException(status_code=422, detail="Description cannot be null.")
    if "description" in changes:
        changes["description"] = changes["description"].strip()
    if "completed" in changes and changes["completed"] is None:
        raise HTTPException(status_code=422, detail="Completed cannot be null.")
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()

    assignments = ", ".join(f"{field} = ?" for field in changes)
    values = tuple(int(value) if field == "completed" else value
                    for field, value in changes.items())
    with connect_database() as connection:
        cursor = connection.execute(
            f"UPDATE tasks SET {assignments} WHERE id = ?",
            values + (task_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found.")
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
    return task_from_row(row)


@app.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int) -> Response:
    with connect_database() as connection:
        cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Task not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


app.mount("/", StaticFiles(directory=Path(__file__).with_name("static"), html=True), name="static")
