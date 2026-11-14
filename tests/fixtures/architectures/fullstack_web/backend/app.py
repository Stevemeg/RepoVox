from backend.repository import add_item, list_items
from fastapi import FastAPI

app = FastAPI()
DATABASE = "items.db"


@app.get("/items")
def read_items():
    return list_items(DATABASE)


@app.post("/items")
def create_item(name: str):
    return add_item(DATABASE, name)
