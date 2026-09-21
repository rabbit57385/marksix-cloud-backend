import copy
import unittest

from pydantic import ValidationError

from marksix_cloud_backend.models import validate_draw


def sample_draw(**changes):
    value = {"draw": "26/102", "date": "2026-09-19",
             "numbers": [5, 8, 11, 14, 19, 31], "special_number": 21}
    value.update(changes)
    return value


class DrawValidationTests(unittest.TestCase):
    def test_valid_draw_and_ball_boundaries(self):
        for numbers, special in (([1, 2, 3, 4, 5, 49], 48), ([2, 3, 4, 5, 6, 7], 1),
                                 ([1, 2, 3, 4, 5, 6], 49)):
            value = sample_draw(numbers=numbers, special_number=special)
            self.assertEqual(validate_draw(value), value)

    def test_exactly_six_mains(self):
        for count in (0, 5, 7):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                validate_draw(sample_draw(numbers=list(range(1, count + 1))))

    def test_rejects_invalid_main_balls_without_coercion(self):
        for bad in (0, 50, -1, None, True, 5.0, "5"):
            with self.subTest(ball=bad), self.assertRaises(ValidationError):
                validate_draw(sample_draw(numbers=[bad, 8, 11, 14, 19, 31]))

    def test_rejects_invalid_special_without_coercion(self):
        for bad in (0, 50, -1, None, True, 21.0, "21"):
            with self.subTest(ball=bad), self.assertRaises(ValidationError):
                validate_draw(sample_draw(special_number=bad))

    def test_rejects_every_pair_of_duplicate_mains(self):
        for first in range(6):
            for second in range(first + 1, 6):
                value = sample_draw()
                value["numbers"][second] = value["numbers"][first]
                with self.subTest(pair=(first, second)), self.assertRaises(ValidationError):
                    validate_draw(value)

    def test_special_must_differ_from_each_main(self):
        for number in sample_draw()["numbers"]:
            with self.subTest(number=number), self.assertRaises(ValidationError):
                validate_draw(sample_draw(special_number=number))

    def test_dates_and_draw_identity(self):
        for changes in ({"date": "2026-02-30"}, {"date": "2025-09-19"},
                        {"date": None}, {"date": "2026-09-19+08:00"},
                        {"draw": "26/000"}, {"draw": "2026/102"}, {"draw": "26/102\n"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_draw(sample_draw(**changes))

    def test_rejects_missing_and_extra_fields(self):
        value = sample_draw()
        del value["special_number"]
        with self.assertRaises(ValidationError):
            validate_draw(value)
        with self.assertRaises(ValidationError):
            validate_draw(sample_draw(unexpected="data"))

    def test_preserves_main_order_and_does_not_mutate_input(self):
        value = sample_draw(numbers=[31, 19, 14, 11, 8, 5])
        before = copy.deepcopy(value)
        self.assertEqual(validate_draw(value), before)
        self.assertEqual(value, before)
