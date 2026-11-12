"""Speech placement is independent of character visibility and voice ownership."""

from typing import Literal

Delivery = Literal["on_screen", "off_screen", "inner", "narration"]
LibraryDelivery = Literal["on_screen", "off_screen", "inner", "narration", "unclassified"]
DELIVERY_DIRECTIONS = {
    "on_screen": "画内对白，出镜说话者开口，口型与台词对应",
    "off_screen": "角色画外发声，不为这句台词添加该角色入画，不安排其口型",
    "inner": "角色内心独白，保持该角色音色，人物不张口、不做说话口型",
    "narration": "叙述旁白，画外叙述，不添加旁白人物或口型",
}
