import express from "express";
import http from "http";
import { WebSocketServer } from "ws";

const app = express();
app.use(express.json());

app.get("/", (_req, res) => {
  res.type("text/html").send(`
    <!doctype html>
    <html><head><meta charset="utf-8"><title>Node Starter</title></head>
    <body style="font-family:Segoe UI,Arial,sans-serif;margin:24px">
      <h2>Node Express Starter</h2>
      <p>Project: <code>express</code></p>
      <p>Domain: <code>express.fake</code></p>
      <p>WebSocket endpoint: <code>/ws</code></p>
    </body></html>
  `);
});

app.get("/health", (_req, res) => {
  res.json({ ok: true, pack: "node-express", domain: "express.fake", project: "express", time: new Date().toISOString() });
});

const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: "/ws" });
wss.on("connection", (socket) => {
  socket.send(JSON.stringify({ ok: true, type: "welcome", project: "express" }));
  socket.on("message", (buf) => {
    socket.send(JSON.stringify({ echo: String(buf), at: new Date().toISOString() }));
  });
});

const port = 3000;
server.listen(port, "127.0.0.1", () => {
  console.log(`Node starter listening on http://127.0.0.1:${port}`);
});
