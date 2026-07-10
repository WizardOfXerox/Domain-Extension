# Dev Environment Packs

`server/new_pack.ps1` now uses real templates from this folder.

Per pack:
- `site/` -> copied into `server/websites/<domain>/`
- `backend/` -> copied into `examples/generated/<domain>-<pack>/`

Supported packs:
- `php-xampp`
- `node-express`
- `wordpress-xampp`
- `laravel`

Example:
```powershell
powershell -ExecutionPolicy Bypass -File server\new_pack.ps1 -Pack php-xampp -Domain shop.fake -Project shop
```

After running:
- domain config is created in `server/websites/shop.fake/directory.json`
- site template files are copied to `server/websites/shop.fake/`
- backend starter files are generated in `examples/generated/shop.fake-php-xampp/`
