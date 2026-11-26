-- Spike 2e. Run as reader A. Expect: denied. Readers with viewer only can't write (preview of D5 case 2).
INSERT INTO `${PROJECT}.spike_rls.fct_alert` (tenant_id, store_id, incident_id, alert_date, priority)
VALUES ('ACC-1001', 'S101', 'INC-SPIKE-READER', '2026-11-01', 'P5');
