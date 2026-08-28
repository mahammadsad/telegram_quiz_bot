-- The v2 dashboard calls the established volatile dashboard projection, which
-- refreshes overdue learner state before reading it.  Marking this wrapper
-- STABLE made PostgREST open a read-only transaction and reject that refresh
-- with SQLSTATE 25006.  The RPC remains service-role-only; this change aligns
-- its declared volatility with the work it already performs.

alter function public.get_user_learning_dashboard_v2(uuid) volatile;
