# -*- coding: utf-8 -*-
"""Plan zapytań: rotacja regionalna i spółkowa."""

import dork_plan as dp


class TestRegionalDorks:
    def test_cztery_regiony_na_run(self):
        out = dp.regional_dorks(100, 4)
        assert len(out) == 4
        assert all(any(r in d for r in dp.REGIONS) for d in out)

    def test_kazdy_region_raz_na_cztery_dni(self):
        seen = set()
        for day in range(1, 5):
            for dork in dp.regional_dorks(day, 4):
                for region in dp.REGIONS:
                    if region in dork:
                        seen.add(region)
        assert seen == set(dp.REGIONS)

    def test_ten_sam_dzien_ten_sam_plan(self):
        assert dp.regional_dorks(77, 4) == dp.regional_dorks(77, 4)

    def test_kolejny_dzien_inne_regiony(self):
        assert dp.regional_dorks(77, 4) != dp.regional_dorks(78, 4)

    def test_zero_wylacza(self):
        assert dp.regional_dorks(10, 0) == []


class TestCompanyDorks:
    def test_rotacja_bez_powtorzen(self):
        out = dp.company_dorks(12, 2)
        assert len(out) == 2
        assert len(set(out)) == 2

    def test_limit_do_liczby_szablonow(self):
        out = dp.company_dorks(12, 99)
        assert len(out) == len(dp.COMPANY_TEMPLATES)


class TestBuildPlan:
    def test_plan_zawiera_baze_i_dodatki(self):
        plan = dp.build_plan(50, base=["bazowy dork"])
        assert plan[0] == "bazowy dork"
        assert len(plan) == 1 + dp.REGIONS_PER_RUN + dp.COMPANIES_PER_RUN

    def test_bez_duplikatow(self):
        plan = dp.build_plan(50)
        assert len(plan) == len(set(plan))

    def test_plan_zmienia_sie_miedzy_dniami(self):
        assert dp.build_plan(50) != dp.build_plan(51)

    def test_domyslny_dzien(self):
        plan = dp.build_plan()
        assert len(plan) >= len(dp.BASE_DORKS)
