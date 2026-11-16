import express from "express";
import { findOrders, placeOrder } from "./orders.js";

const app = express();

app.get("/api/orders", async (req, res) => {
  res.json(await findOrders(req.query.customer));
});

app.post("/api/orders", async (req, res) => {
  const order = await placeOrder(req.body);
  res.status(201).json(order);
});

app.listen(8080);
