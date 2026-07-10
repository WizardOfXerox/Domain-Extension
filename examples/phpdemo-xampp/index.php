<?php
declare(strict_types=1);

$name = isset($_GET['name']) ? trim((string)$_GET['name']) : '';
if ($name === '') {
    $name = 'Guest';
}
$time = date('Y-m-d H:i:s');
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PHP Demo via Domain Extension</title>
  <style>
    body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #111827; background: #f8fafc; }
    .card { max-width: 760px; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; }
    .muted { color: #4b5563; }
    .ok { color: #047857; font-weight: 600; }
    code { background: #f1f5f9; padding: 2px 6px; border-radius: 6px; }
    input, button { font: inherit; padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 8px; }
    button { cursor: pointer; background: #e2e8f0; }
  </style>
</head>
<body>
  <div class="card">
    <h2>PHP + XAMPP Integration Demo</h2>
    <p class="ok">Dynamic PHP is running behind <code>https://phpdemo.fake/</code>.</p>
    <p class="muted">Server time (PHP): <strong><?php echo htmlspecialchars($time, ENT_QUOTES, 'UTF-8'); ?></strong></p>

    <form method="get" action="/">
      <label for="name">Name:</label>
      <input id="name" name="name" value="<?php echo htmlspecialchars($name, ENT_QUOTES, 'UTF-8'); ?>" />
      <button type="submit">Render</button>
    </form>

    <p>Hello, <strong><?php echo htmlspecialchars($name, ENT_QUOTES, 'UTF-8'); ?></strong>.</p>
    <p><a href="/api.php">Open JSON endpoint</a></p>
  </div>
</body>
</html>
