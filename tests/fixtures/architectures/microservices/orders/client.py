import requests


def reserve(order):
    response = requests.post("http://inventory:8000/reserve", json=order, timeout=5)
    return response.status_code
