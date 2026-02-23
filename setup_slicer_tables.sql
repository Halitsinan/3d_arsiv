-- Printer Yönetimi için Tablolar

-- Printerlar tablosu
CREATE TABLE IF NOT EXISTS printers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    model VARCHAR(100),
    bed_width INTEGER,
    bed_depth INTEGER,
    bed_height INTEGER,
    nozzle_diameter DECIMAL(3,2) DEFAULT 0.4,
    max_print_speed INTEGER DEFAULT 150,
    profile_path TEXT,
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Filamentler tablosu
CREATE TABLE IF NOT EXISTS filaments (
    id SERIAL PRIMARY KEY,
    printer_id INTEGER REFERENCES printers(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    material VARCHAR(50),
    color VARCHAR(50),
    brand VARCHAR(50),
    nozzle_temp INTEGER DEFAULT 210,
    bed_temp INTEGER DEFAULT 60,
    print_speed INTEGER DEFAULT 100,
    flow_ratio DECIMAL(4,2) DEFAULT 1.0,
    retraction_length DECIMAL(3,1) DEFAULT 0.8,
    notes TEXT,
    is_calibrated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Slice işleri tablosu (log için)
CREATE TABLE IF NOT EXISTS slice_jobs (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
    printer VARCHAR(200),
    filament VARCHAR(200),
    process VARCHAR(200),
    output_file TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- İndeksler
CREATE INDEX IF NOT EXISTS idx_filaments_printer ON filaments(printer_id);
CREATE INDEX IF NOT EXISTS idx_slice_jobs_asset ON slice_jobs(asset_id);
CREATE INDEX IF NOT EXISTS idx_slice_jobs_status ON slice_jobs(status);
