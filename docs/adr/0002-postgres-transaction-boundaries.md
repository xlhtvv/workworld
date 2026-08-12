# Serialize scarce resources in PostgreSQL transactions

Run state changes, sealed-candidate selection with slot reservation, and ledger holds use PostgreSQL constraints plus row locks in one transaction. Application-only locks and Redis locks were rejected because correctness must survive worker retries and process loss, while Redis remains suitable for delivery and rate-limit coordination rather than the source of truth.
