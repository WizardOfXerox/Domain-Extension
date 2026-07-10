import React from "react";
import ReactDOM from "react-dom/client";

function App() {
  return (
    <div style={{ padding: "2rem", fontFamily: "system-ui, sans-serif" }}>
      <h1>shop</h1>
      <p>Vite + React app running on <code>shop.fake</code></p>
      <p>Backend origin: <code>http://127.0.0.1:5173</code></p>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
