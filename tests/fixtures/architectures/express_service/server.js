const express = require("express");
const { listItems, addItem } = require("./items");

const app = express();
app.use(express.json());

app.get("/items", async (req, res) => {
  const rows = await listItems(req.query.tag);
  res.json(rows);
});

app.post("/items", createItem);

async function createItem(req, res) {
  const saved = await addItem(req.body.name);
  res.status(201).json(saved);
}

app.listen(3000);
