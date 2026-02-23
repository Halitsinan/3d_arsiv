UPDATE assets SET thumbnail_attempts = 0
WHERE thumbnail_blob IS NULL 
  AND (filepath LIKE '%drive.google.com%' OR filepath LIKE '%/d/%');
SELECT COUNT(*) AS resetlenen FROM assets WHERE thumbnail_blob IS NULL AND thumbnail_attempts = 0;
