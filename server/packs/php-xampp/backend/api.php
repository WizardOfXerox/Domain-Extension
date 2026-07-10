<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
echo json_encode([
    'ok' => true,
    'pack' => '__PACK__',
    'domain' => '__DOMAIN__',
    'project' => '__PROJECT__',
    'time' => date('c')
], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
