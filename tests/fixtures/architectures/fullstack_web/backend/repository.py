import sqlite3


def list_items(database):
    connection = sqlite3.connect(database)
    return connection.execute("SELECT name FROM items").fetchall()


def add_item(database, name):
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO items(name) VALUES (?)", (name,))
    connection.commit()
    return name
