"""
grants_ingest — ingestion pipeline and funder registry for grant discovery.

App boundary: adapters, content-addressed object store, append-only event log,
registry models (Funder, Program, OpportunityInstance, HistoricalGrant), and
management commands. Does not own the user-facing coordinator/donor surface or
the AI extraction logic for Tier B/C sources (Component 2).
"""
