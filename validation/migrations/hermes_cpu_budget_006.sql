DROP TRIGGER agent_concurrency_reservation_transition;
CREATE TRIGGER agent_concurrency_reservation_transition BEFORE UPDATE ON agent_concurrency_reservations
WHEN NEW.run_id IS NOT OLD.run_id OR NEW.request_key IS NOT OLD.request_key
  OR NEW.root_run_id IS NOT OLD.root_run_id OR NEW.request_digest IS NOT OLD.request_digest
  OR NEW.lease_owner IS NOT OLD.lease_owner OR NEW.lease_epoch IS NOT OLD.lease_epoch
  OR NEW.created_at IS NOT OLD.created_at
  OR NOT ((OLD.state = 'ACTIVE' AND NEW.state IN ('UNKNOWN','RELEASED'))
      OR (OLD.state = 'UNKNOWN' AND NEW.state = 'RELEASED' AND EXISTS (
          SELECT 1 FROM hermes_cpu_final_exits f JOIN hermes_vm_run_bindings b
            ON b.run_id=f.run_id AND b.request_key=f.request_key
          WHERE f.run_id=OLD.run_id AND f.request_key=OLD.request_key
            AND f.lease_epoch=OLD.lease_epoch AND b.lease_owner=OLD.lease_owner
            AND b.lease_epoch=f.lease_epoch AND b.vm_id=f.vm_id
            AND b.boot_id=f.boot_id AND b.unit_name=f.unit
            AND f.source='SLICE_CPU_NSEC_V1'
      )))
BEGIN SELECT RAISE(ABORT, 'concurrency reservation is immutable'); END;
