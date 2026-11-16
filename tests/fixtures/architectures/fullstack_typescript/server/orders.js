import { MongoClient } from "mongodb";

const client = new MongoClient("mongodb://orders-db:27017");

export async function findOrders(customer) {
  return client.db("shop").collection("orders").find({ customer }).toArray();
}

export async function placeOrder(order) {
  await client.db("shop").collection("orders").insertOne(order);
  return order;
}
