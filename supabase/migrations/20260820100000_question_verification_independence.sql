-- Record generator and verifier identities separately. Equality is never
-- sufficient evidence of an independent verification pass.

alter table public.question_generation_audits
    add column if not exists generator_provider text,
    add column if not exists generator_model text;

create index if not exists idx_question_generation_audits_models
    on public.question_generation_audits (
        generator_provider, generator_model, verifier_provider, verifier_model
    );

create or replace function public.get_question_verification_independence_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select jsonb_build_object(
        'ready',
            exists (
                select 1 from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'question_generation_audits'
                  and column_name = 'generator_model'
            ),
        'migration_version', '20260820100000',
        'separate_generator_verifier_identity', true,
        'same_model_is_not_independent', true
    );
$$;

revoke all on function public.get_question_verification_independence_contract()
    from public, anon, authenticated;
grant execute on function public.get_question_verification_independence_contract()
    to service_role;
