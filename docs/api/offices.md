# Office selection and contact validation

`setup.list_offices` (GET, authenticated) returns `{offices, selected_office}`.
Membership is resolved by the same `login_state.accessible_offices` used by
`session.select_office`; no new membership or role is granted. The card fields
are returned to members. Owner identity and contact details require the existing
native read permission on ASOUD Company Setup.

`setup.set_default_office(company)` (POST) delegates to `session.select_office`.
An employee may select their authorised office without an accounting role.
Unlisted offices and forced-password-change sessions are refused. A failure
must not be treated as a successful server selection. `get_setup_status()` uses
the saved user default, rather than arbitrarily choosing a different office.

`setup.save_office` and `onboarding.create_first_office` keep their existing
creation/edit permission gates. National identity checksums remain unchanged:
personal identity is exactly 10 digits; legal identity exactly 11. `phone`
retains its existing mobile meaning (11 digits beginning 09). New optional
`landline` is 11 digits beginning 0; Persian/Arabic digits are normalized.
An omitted landline in an older client does not erase its stored value.

Deployment: `bench migrate` adds the optional ASOUD Company Setup.landline field.
No existing identity, office, role, profile or user is migrated or deleted.
