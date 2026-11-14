from fastapi import FastAPI
from inventory.stock import adjust

app = FastAPI()


@app.post("/reserve")
def reserve_stock(item: str):
    return adjust(item)
