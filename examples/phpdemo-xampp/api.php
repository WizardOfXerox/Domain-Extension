<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

echo json_encode([
    'ok' => true,
    'message' => 'Hello from PHP backend',
    'time' => date('c'),
    'request' => [
        'method' => $_SERVER['REQUEST_METHOD'] ?? '',
        'uri' => $_SERVER['REQUEST_URI'] ?? '',
        'host' => $_SERVER['HTTP_HOST'] ?? '',
        'x_forwarded_host' => $_SERVER['HTTP_X_FORWARDED_HOST'] ?? '',
        'x_forwarded_proto' => $_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '',
    ],
], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
