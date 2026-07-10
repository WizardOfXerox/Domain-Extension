<?php
declare(strict_types=1);

$name = isset($_GET['name']) ? trim((string)$_GET['name']) : 'Guest';
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>php PHP Starter</title>
  <style>
    body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #111827; background: #f8fafc; }
    .card { max-width: 860px; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 18px; }
    code { background: #f1f5f9; border-radius: 6px; padding: 2px 6px; }
  </style>
</head>
<body>
  <div class="card">
    <h2>PHP XAMPP Starter</h2>
    <p>Project: <code>php</code></p>
    <p>Domain mapping target: <code>php.fake</code></p>
    <p>Hello, <strong><?php echo htmlspecialchars($name, ENT_QUOTES, 'UTF-8'); ?></strong>.</p>
    <p><a href="/php/api.php">JSON API</a></p>
  </div>
</body>
</html>
