-- DiBeKho Cloud v6: owner commands. The owner (the 'desktop' account) can do from the web what the app does; the main
-- machine carries each command out the next time it is open (core/cloud/commands.py). Staff keep exactly what they had:
-- an 'editor' may send only the three request kinds, everything else needs the owner's account.
-- Run once in the Supabase SQL editor (after 001..005). Fresh installs already have this in 001_init.sql.

alter table public.web_inbox drop constraint if exists web_inbox_kind_check;
alter table public.web_inbox add constraint web_inbox_kind_check check (kind in (
    'receipt', 'delivery_file', 'stock_count',
    'cmd_transfer', 'cmd_trial', 'cmd_product_add', 'cmd_product_edit', 'cmd_product_merge',
    'cmd_customer_merge', 'cmd_cancel_doc', 'cmd_set_location', 'cmd_receipt_edit'));

drop policy if exists inbox_insert on public.web_inbox;
create policy inbox_insert on public.web_inbox for insert with check (
    created_by = auth.uid()
    and (public.my_role() = 'desktop'
         or (public.my_role() = 'editor' and kind in ('receipt', 'delivery_file', 'stock_count'))));
