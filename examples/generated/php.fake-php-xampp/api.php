<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
echo json_encode([
    'ok' => true,
    'pack' => 'php-xampp',
    'domain' => 'php.fake',
    'project' => 'php',
    'time' => date('c')
], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
