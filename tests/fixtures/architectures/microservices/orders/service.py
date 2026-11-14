from fastapi import FastAPI
from orders.client import reserve

app = FastAPI()


@app.post("/orders")
def create_order(order: dict):
    status = reserve(order)
    return {"reserved": status}
