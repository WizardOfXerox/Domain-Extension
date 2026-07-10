import React from "react";
import ReactDOM from "react-dom/client";

function App() {
  return (
    <div style={{ padding: "2rem", fontFamily: "system-ui, sans-serif" }}>
      <h1>__PROJECT__</h1>
      <p>Vite + React app running on <code>__DOMAIN__</code></p>
      <p>Backend origin: <code>__ORIGIN__</code></p>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
