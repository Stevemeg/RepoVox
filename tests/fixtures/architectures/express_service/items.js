const { Pool } = require("pg");

const pool = new Pool();

async function listItems(tag) {
  const result = await pool.query("SELECT name FROM items WHERE tag = $1", [tag]);
  return result.rows;
}

async function addItem(name) {
  const result = await pool.query("INSERT INTO items(name) VALUES ($1) RETURNING name", [name]);
  return result.rows[0];
}

module.exports = { listItems, addItem };
