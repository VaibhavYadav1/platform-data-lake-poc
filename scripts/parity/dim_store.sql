with poc1 as (
  select s.id as store_id, s.name as store_name, s.number as store_number, s.fk_brand as brand_id, s.brand,
         b.is_active as brand_is_active, s.country, s.state, s.city, s.region, s.department, s.district,
         s.is_active, s.hierarchy_complete
  from `{baseline_project}.poc1_baseline.dim_store` as s
  left join `{baseline_project}.poc1_baseline.dim_brand` as b on b.id = s.fk_brand
),
p2 as (
  select store_id, store_name, store_number, brand_id, brand, brand_is_active, country, state, city, region,
         department, district, is_active, hierarchy_complete
  from `{project}.dbt_{user}_build.dim_store`
)
select 'only_in_poc1' as side, * from (select * from poc1 except distinct select * from p2)
union all
select 'only_in_poc2' as side, * from (select * from p2 except distinct select * from poc1)
