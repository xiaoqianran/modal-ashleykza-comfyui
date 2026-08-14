#!/usr/bin/env python3
"""Build examples/campus-days-storyboard.json (100 FLUX.2 frames, Shinkai look)."""

from __future__ import annotations

import json
from pathlib import Path

# FLUX.2: natural-language sentences; subject → action → environment → light.
# Style is locked once and appended to every frame so 100 shots share one look.
# Visual language: Makoto Shinkai / CoMix Wave Films (Your Name, Weathering With You,
# 5 Centimeters per Second) — not live-action photography, not flat TV anime.

STYLE = (
    "Cinematic anime film still in the visual language of Makoto Shinkai and CoMix Wave Films. "
    "Hyper-detailed painted background, layered volumetric clouds filling most of the sky, "
    "anamorphic lens flare, crepuscular god rays, sparkling airborne light particles, "
    "saturated cobalt-blue to amber-orange color grade, wet-surface reflections when it rains, "
    "nostalgic emotional quiet. Anime characters slightly small in the frame so the sky and "
    "architecture can breathe. Painted key visual, not live-action photography, not generic TV anime."
)

AOI = (
    "Aoi, a 16-year-old Japanese high-school girl with long black hair and a small red ribbon, "
    "sailor-style uniform, large clear eyes"
)
HARUTO = (
    "Haruto, a 16-year-old Japanese high-school boy with slightly messy dark hair, "
    "navy school blazer and a loosened striped tie"
)


def frame(scene: str) -> str:
    return f"{scene.strip()} {STYLE}"


ACTS = [
    ("开学清晨", [
        (
            "001",
            "校门晨曦",
            frame(
                f"Wide establishing shot of a suburban Japanese high-school gate at dawn. "
                f"{AOI} and {HARUTO} walk uphill under a sky of towering peach and gold cumulonimbus. "
                f"Cherry trees, telephone poles, and a distant clock tower. Pale god rays cut the mist."
            ),
        ),
        (
            "002",
            "电车到站",
            frame(
                f"{AOI} steps off a morning commuter train onto a quiet suburban platform. "
                f"Sun flares through the carriage windows; tracks recede toward layered morning clouds. "
                f"Other students in sailor uniforms blur past. A 5 Centimeters per Second station mood."
            ),
        ),
        (
            "003",
            "樱花大道",
            frame(
                f"{AOI} and {HARUTO} walk a cherry-lined slope to school, petals drifting like snow. "
                f"Behind them a vast spring sky of white stratus over deep blue. "
                f"Petals catch the sun as tiny sparks. Soft two-shot, characters small under the trees."
            ),
        ),
        (
            "004",
            "铁路道口",
            frame(
                f"{AOI} waits at a suburban railway crossing, bag hugged to her chest, "
                f"red crossing lights blinking. A train rushes past with step-printed glass reflections. "
                f"Crepuscular rays fan between the cars. Classic Shinkai level-crossing composition."
            ),
        ),
        (
            "005",
            "教学楼仰望",
            frame(
                f"Low-angle view of a red-brick school building against an enormous afternoon sky. "
                f"Tiny silhouettes of students on the stairs. Windows flash like gold. "
                f"Clouds stacked in painterly layers, almost more important than the building."
            ),
        ),
        (
            "006",
            "天台相遇",
            frame(
                f"{AOI} and {HARUTO} meet for the first time on the school rooftop, "
                f"chain-link fence and water tower behind them. Wind lifts her ribbon. "
                f"A cathedral of clouds fills the upper two-thirds of the frame. Shy, bright eyes."
            ),
        ),
        (
            "007",
            "走廊光柱",
            frame(
                f"Empty school hallway just after the first bell. Dust motes and chalk sparkle in a "
                f"diagonal shaft of window light. {AOI} runs past with her bag bouncing, "
                f"hair and ribbon catching the flare. Quiet before the rush."
            ),
        ),
        (
            "008",
            "教室窗云",
            frame(
                f"From inside a wooden classroom, looking out through tall open windows at a "
                f"sky of rolling summer clouds. Empty desks in the foreground, curtains breathing. "
                f"The clouds are rendered with extreme painted detail, almost a character themselves."
            ),
        ),
        (
            "009",
            "同桌侧光",
            frame(
                f"{AOI} and {HARUTO} sit as desk-mates. Warm late-morning light from the window "
                f"rims their profiles; outside, a slice of blue sky and a single power line. "
                f"Open textbooks between them. Gentle, almost silent smile."
            ),
        ),
        (
            "010",
            "黑板与天空",
            frame(
                f"A kind homeroom teacher writes Welcome New Semester on a green blackboard "
                f"while sunlight from the side windows turns the chalk dust into gold. "
                f"Rows of sailor uniforms. Beyond the windows, infinite layered clouds."
            ),
        ),
    ]),
    ("课堂时光", [
        (
            "011",
            "数学课光斑",
            frame(
                f"Geometry proofs on a green blackboard, white chalk lines catching window glare. "
                f"{HARUTO} copies notes, a bright anamorphic flare streaking across the classroom. "
                f"Outside, a slice of cobalt sky. Quiet concentration."
            ),
        ),
        (
            "012",
            "窗边听讲",
            frame(
                f"Close portrait of {AOI} listening in class, chin in her hand, eyes reflecting "
                f"the window. Behind her, bokeh of classmates and a sky full of luminous clouds. "
                f"Soft rim light on her hair and red ribbon."
            ),
        ),
        (
            "013",
            "课桌纸条",
            frame(
                f"A folded note slides across a wooden desk between {AOI} and {HARUTO}. "
                f"Only hands, sailor sleeves, and a stripe of sunset on the wood. "
                f"The rest of the classroom falls into warm shadow. Secret, tender."
            ),
        ),
        (
            "014",
            "英语朗读",
            frame(
                f"{HARUTO} stands at the podium reading English, sunlight turning the pages gold. "
                f"{AOI} follows along in her seat, a faint smile. Classroom flags, vocabulary posters, "
                f"and through the windows a huge peaceful sky."
            ),
        ),
        (
            "015",
            "化学室蓝焰",
            frame(
                f"Chemistry lab at dusk. Students in goggles watch a small blue flame. "
                f"Glassware catches orange window light. Beyond the lab windows, a violet-orange "
                f"twilight sky. Science as a quiet miracle."
            ),
        ),
        (
            "016",
            "显微镜光",
            frame(
                f"{AOI} looks into a microscope while {HARUTO} sketches in a notebook. "
                f"A single sunbeam from a high window ignites floating dust. "
                f"Stainless benches, specimen slides, and a square of blazing sky."
            ),
        ),
        (
            "017",
            "美术室北窗",
            frame(
                f"Art room with north-facing windows. Students draw still-life vases; charcoal on fingers. "
                f"The windows show a vast cloudscape like a painted mural. "
                f"Easels, wooden floors, and drifting light motes."
            ),
        ),
        (
            "018",
            "音乐室钢琴",
            frame(
                f"{AOI} plays piano by open windows while classmates tune violins. "
                f"Late-afternoon gold floods the wooden floor. Sheet music lifts in the breeze. "
                f"Outside, telephone wires cut across a glowing sky."
            ),
        ),
        (
            "019",
            "操场集合",
            frame(
                f"PE class lining up on a green field under a sky of towering white clouds. "
                f"Tiny students in white gym clothes. Distant clock tower and goal posts. "
                f"The sky occupies most of the frame, as in a Shinkai establishing shot."
            ),
        ),
        (
            "020",
            "课间天台风",
            frame(
                f"Between classes, {AOI} and friends lean on the rooftop fence, hair and ribbons in the wind. "
                f"The town spreads below in hyper-detailed miniature. "
                f"Clouds race overhead with dramatic volumetric shadows."
            ),
        ),
    ]),
    ("午间与放学路", [
        (
            "021",
            "食堂窗景",
            frame(
                f"School cafeteria at lunch. Steam from bowls, chatter as painted background motion. "
                f"{AOI} and {HARUTO} sit by a huge window showing summer clouds over the sports field. "
                f"Interior warmth against the cool blue outside."
            ),
        ),
        (
            "022",
            "便当分享",
            frame(
                f"Four friends share homemade bento on the rooftop, chopsticks and colorful side dishes. "
                f"Above them an ocean of afternoon cumulonimbus. "
                f"Wind, laughter, and sparkling rice grains catching the sun."
            ),
        ),
        (
            "023",
            "天台独坐",
            frame(
                f"{HARUTO} sits alone on the rooftop with a sketchbook, headphones around his neck. "
                f"His small figure against a cathedral sky of gold-edged clouds. "
                f"Quiet, slightly lonely, hopeful."
            ),
        ),
        (
            "024",
            "自动贩卖机",
            frame(
                f"{AOI} buys canned coffee from a glowing vending machine in a shaded school corridor. "
                f"The machine's colored lights contrast with the blazing white-blue sky at the corridor's end. "
                f"Everyday Shinkai still life."
            ),
        ),
        (
            "025",
            "银杏树荫",
            frame(
                f"{AOI} and a friend walk slowly along a ginkgo path after lunch. "
                f"Dappled god rays through dense leaves. Distant students like tiny notes on the field. "
                f"Deep green against a pale luminous sky."
            ),
        ),
        (
            "026",
            "放学电车窗",
            frame(
                f"{AOI} rides the evening train home, forehead near the glass. "
                f"The window holds a double image: her face and a burning orange sky over suburban rooftops. "
                f"Step-printed reflections, telephone poles streaming past."
            ),
        ),
        (
            "027",
            "人行天桥",
            frame(
                f"{AOI} and {HARUTO} cross a pedestrian overpass after school, bags on shoulders. "
                f"Below, a river of cars and a railway. Above, a monumental sunset. "
                f"They are small silhouettes on the bridge."
            ),
        ),
        (
            "028",
            "便利店黄昏",
            frame(
                f"A corner convenience store at blue hour, interior fluorescent against indigo sky. "
                f"{HARUTO} waits outside with two ice creams. {AOI} appears from the sliding door. "
                f"Wet pavement optional sheen, nostalgic suburban quiet."
            ),
        ),
        (
            "029",
            "电线与晚霞",
            frame(
                f"Looking up along a row of wooden utility poles and tangled wires, "
                f"the sky a gradient from fire-orange to deep violet. "
                f"A single crow. No people, or only a tiny cyclist far below. Pure Shinkai sky portrait."
            ),
        ),
        (
            "030",
            "坡道回家",
            frame(
                f"{AOI} walks a steep residential slope between old houses, bag bouncing, "
                f"the sun exploding behind the hill. Lens flare, long shadows, cicada-season heat haze. "
                f"A 5 Centimeters per Second after-school road."
            ),
        ),
    ]),
    ("图书馆与社团", [
        (
            "031",
            "图书馆光柱",
            frame(
                f"University-style high-school library with tall windows. "
                f"Volumetric light falls between book stacks like water. "
                f"{AOI} is a small figure reaching for a novel. Dust sparkles."
            ),
        ),
        (
            "032",
            "窗边自习",
            frame(
                f"{AOI} and {HARUTO} study at a library window desk. Lamps, notes, two cups of tea. "
                f"Outside: rain-dark trees and a silver sky. "
                f"Glass reflections overlay their faces with clouds."
            ),
        ),
        (
            "033",
            "夜自习蓝窗",
            frame(
                f"Evening study hall. Desk lamps make warm islands; the windows are deep ultramarine. "
                f"Students bent over books. A clock on the wall. "
                f"The blue outside is as saturated as a Shinkai night."
            ),
        ),
        (
            "034",
            "天台望远镜",
            frame(
                f"Astronomy club on the roof at dusk. {HARUTO} aims a small telescope; {AOI} looks up with wonder. "
                f"The first stars puncture a violet sky still holding orange at the horizon. "
                f"City lights beginning far below."
            ),
        ),
        (
            "035",
            "摄影社外拍",
            frame(
                f"Photography club on the lawn. A student frames {AOI} against a sky of epic clouds. "
                f"Camera straps, a silver reflector catching sun. "
                f"The real subject is the weather behind her."
            ),
        ),
        (
            "036",
            "礼堂彩排",
            frame(
                f"Drama club on a small wooden stage, a single warm spotlight. "
                f"Empty seats dissolve into darkness. A side door open to blinding afternoon. "
                f"Theatrical dust in the beam."
            ),
        ),
        (
            "037",
            "体育馆镜面",
            frame(
                f"Dance club in a gym with high windows. Sneakers on polished wood that reflects the sky. "
                f"Mirrored wall, motion, and a slice of brilliant clouds through clerestory glass."
            ),
        ),
        (
            "038",
            "天文台开顶",
            frame(
                f"A small campus observatory dome opening at twilight. Silhouettes of students. "
                f"The sky is a painted gradient of magenta, indigo, and early stars. "
                f"Sense of weather-as-wonder, like Weathering With You."
            ),
        ),
        (
            "039",
            "文化祭灯笼",
            frame(
                f"Paper lanterns strung between ginkgo trees on the school lawn at festival dusk. "
                f"Booths, steam, and tiny students. The sky still holds leftover gold. "
                f"Lantern light mixing with the last sun."
            ),
        ),
        (
            "040",
            "广播室黄昏",
            frame(
                f"Tiny school radio booth. {AOI} and {HARUTO} lean toward microphones. "
                f"Mixing-board LEDs, playlist notes. Through a small window, the sky is on fire. "
                f"Cozy interior against epic exterior."
            ),
        ),
    ]),
    ("四季校园", [
        (
            "041",
            "春雨透明伞",
            frame(
                f"{AOI} walks the empty running track under a transparent umbrella in light spring rain. "
                f"Puddles mirror a silver-blue sky. Fresh buds, wet red lanes, soft rain curtains. "
                f"Melancholy and beautiful."
            ),
        ),
        (
            "042",
            "雨后彩虹",
            frame(
                f"After the rain, a vivid rainbow arcs over the school clock tower. "
                f"Students with folded umbrellas point upward. Puddles hold the whole sky. "
                f"Air full of glittering droplets."
            ),
        ),
        (
            "043",
            "初夏蝉鸣",
            frame(
                f"Blazing early summer. {AOI} eats watermelon under plane trees, white sailor collar bright. "
                f"Heat shimmer over the distant field. A sky so blue it feels painted. "
                f"Deep leaf-shadow and sparkle."
            ),
        ),
        (
            "044",
            "荷塘晚风",
            frame(
                f"{AOI} and {HARUTO} sit on a wooden bridge over a campus lotus pond at blue hour. "
                f"Sharing one pair of earphones. Moon and clouds doubled in the water. "
                f"Firefly-like sparks near the reeds."
            ),
        ),
        (
            "045",
            "银杏金雨",
            frame(
                f"Autumn avenue buried in golden ginkgo leaves. Students kick the leaves walking to class. "
                f"The sky is a clear cold blue; the trees burn amber. "
                f"Leaves in the air like slow sparks."
            ),
        ),
        (
            "046",
            "枫叶长椅",
            frame(
                f"{HARUTO} reads on a bench among falling maple leaves, thermos steaming. "
                f"Bokeh of red and gold around him. Behind, a huge quiet autumn sky. "
                f"Nostalgia you can almost hear."
            ),
        ),
        (
            "047",
            "初雪校舍",
            frame(
                f"First snow dusts the red-brick school and bare branches. "
                f"Students in coats photograph the scene; breath hangs in the air. "
                f"A pale winter sun and a sky of thin, luminous clouds."
            ),
        ),
        (
            "048",
            "雪夜教室",
            frame(
                f"Heated classroom at night while snow falls past the tall windows in slow streaks. "
                f"Warm interior lamps versus cold blue-white outside. "
                f"{AOI} cups a mug, watching the snow as if it were a movie."
            ),
        ),
        (
            "049",
            "春日重逢",
            frame(
                f"New spring. Fuller cherry blossoms than last year. "
                f"{AOI} and {HARUTO} hug near the school gate, petals swirling, sky enormous and kind. "
                f"Renewal, almost too bright to look at."
            ),
        ),
        (
            "050",
            "夏至积雨云",
            frame(
                f"Midsummer twilight. A colossal cumulonimbus towers over the clock tower, "
                f"lit from within like a lantern. Tiny graduates rehearse on the lawn below. "
                f"The cloud is the protagonist."
            ),
        ),
    ]),
    ("青春与心跳", [
        (
            "051",
            "天台晚风",
            frame(
                f"{AOI}, {HARUTO}, and a friend sit on the rooftop at sunset, legs behind the safe fence. "
                f"The town is a carpet of gold windows. Wind, snacks, secrets. "
                f"Sky of layered fire and violet."
            ),
        ),
        (
            "052",
            "教室生日",
            frame(
                f"After the last bell, classmates surprise {AOI} with a small cake. Candlelight on faces. "
                f"Handmade banner. Through the windows, a deep blue evening. "
                f"Warm indoor gold versus cool sky."
            ),
        ),
        (
            "053",
            "雨中共伞",
            frame(
                f"{HARUTO} holds a dark umbrella over {AOI} as they cross a rainy school courtyard. "
                f"Shoulders almost touching. Stone tiles full of sky-reflections. "
                f"Gray-blue rain light with a single warm window behind them."
            ),
        ),
        (
            "054",
            "单车后座",
            frame(
                f"{AOI} rides on the back of {HARUTO}'s bicycle down a tree-lined slope at dusk. "
                f"Her arms open for balance, ribbon flying. Long shadows, huge amber sky. "
                f"Motion implied by hair and leaves, not blurry smearing."
            ),
        ),
        (
            "055",
            "考前加油",
            frame(
                f"Friends form a circle in a sunlit hallway before exams, hands stacked. "
                f"A window at the end of the corridor explodes with morning god rays. "
                f"Determined smiles, backpacks at their feet."
            ),
        ),
        (
            "056",
            "雨夜便利店",
            frame(
                f"{AOI} and {HARUTO} in hoodies buy instant noodles at a 24-hour shop after studying. "
                f"Rain needles the glass door. Interior fluorescent versus wet indigo street. "
                f"Tired, happy faces. Classic Shinkai night still."
            ),
        ),
        (
            "057",
            "草坪吉他",
            frame(
                f"{HARUTO} plays acoustic guitar on the lawn at golden hour; {AOI} sings softly. "
                f"Sheet music weighted by stones. Behind them, a sky of molten clouds. "
                f"Lens flare across the strings."
            ),
        ),
        (
            "058",
            "台阶合影",
            frame(
                f"Six friends squeeze onto stone steps for a self-timer photo, one running into frame. "
                f"Behind them the school and an operatic sky. "
                f"Genuine messy smiles, key-visual poster energy."
            ),
        ),
        (
            "059",
            "看台和解",
            frame(
                f"After a quarrel, {AOI} and {HARUTO} sit on empty bleachers. He offers a canned soda. "
                f"Awkward half-smiles. The field is vast; the evening sky even vaster. "
                f"Silence filling with relief."
            ),
        ),
        (
            "060",
            "毕业墙夕照",
            frame(
                f"Students write on a temporary memory wall in the courtyard at sunset. "
                f"Polaroids, colorful markers, overlapping hands. "
                f"The wall is backlit; the sky behind it is a wash of rose and gold."
            ),
        ),
    ]),
    ("节庆与天气", [
        (
            "061",
            "文化祭全景",
            frame(
                f"Wide shot of the school cultural festival on the main quad. "
                f"Booths, lanterns, crowds of tiny students. "
                f"Late-afternoon clouds stacked like continents. A Your Name festival afternoon."
            ),
        ),
        (
            "062",
            "浴衣夏祭",
            frame(
                f"{AOI} in a pale yukata walks a summer festival path of paper lanterns. "
                f"{HARUTO} in a simple yukata beside her. Sparklers, goldfish scooping stalls, "
                f"and a sky still holding twilight fire."
            ),
        ),
        (
            "063",
            "烟花远眺",
            frame(
                f"From the school rooftop, distant fireworks bloom over the town. "
                f"{AOI} and {HARUTO} watch, faces lit in changing color. "
                f"Smoke, sparks, and a deep summer night sky."
            ),
        ),
        (
            "064",
            "合唱舞台光",
            frame(
                f"School choir on stage in matching uniforms, mouths open in harmony. "
                f"A side door leaks blazing sunset into the dark auditorium. "
                f"Dust and emotion in the spotlight."
            ),
        ),
        (
            "065",
            "辩论馆窗",
            frame(
                f"High-school debate in a lecture hall. Two teams at podiums. "
                f"Behind the speakers, a wall of windows showing racing storm clouds. "
                f"Intellectual tension plus weather drama."
            ),
        ),
        (
            "066",
            "湖边马拉松",
            frame(
                f"Charity campus run along a lake. Runners as small colorful notes. "
                f"Morning mist, mirrored sky on the water, flags snapping. "
                f"Huge peaceful clouds."
            ),
        ),
        (
            "067",
            "操场露天电影",
            frame(
                f"Night outdoor movie on the athletic field. A projector beam cuts faint mist. "
                f"Students on blankets. Stars and a huge moon. "
                f"The screen glows like a second window in the dark."
            ),
        ),
        (
            "068",
            "中秋校庭",
            frame(
                f"Mid-autumn evening. Paper lanterns along a path; students share mooncakes. "
                f"A full moon rises behind the library dome, clouds drifting like silk. "
                f"Warm lantern gold versus cold moonlight."
            ),
        ),
        (
            "069",
            "冬至走廊灯",
            frame(
                f"Students hang paper snowflakes and warm lights in the main hallway before winter break. "
                f"A ladder, tape, laughter. Through the end-window: early dusk, first snow. "
                f"Cozy institutional charm."
            ),
        ),
        (
            "070",
            "跨年火花",
            frame(
                f"Friends on a dorm rooftop with sparklers at year's end. Breath in cold air. "
                f"City lights below, a clear winter sky of sharp stars above. "
                f"Joyful faces in sparkler-orange."
            ),
        ),
    ]),
    ("备考与成长", [
        (
            "071",
            "黎明书桌",
            frame(
                f"{AOI} reviews notes at a dorm desk before dawn. Desk lamp, stacked papers, "
                f"pale peach light seeping through curtains. Determined calm. "
                f"The sky outside is just beginning to glow."
            ),
        ),
        (
            "072",
            "窗边错题",
            frame(
                f"Close-up of hands rewriting math in a neat notebook, red pen, eraser crumbs. "
                f"A window behind the desk shows a quiet morning sky and a single power line. "
                f"Discipline as a still life."
            ),
        ),
        (
            "073",
            "放学答疑",
            frame(
                f"After class, a teacher explains a physics problem to {AOI} and {HARUTO} at the blackboard. "
                f"The classroom is emptying. Late sun turns the windows into gold panels. "
                f"Mentorship, dust, and silence."
            ),
        ),
        (
            "074",
            "通宵自习室",
            frame(
                f"24-hour study room at 1 a.m. A few students, coffee, dim lamps. "
                f"Floor-to-ceiling glass shows a sleeping city and a navy sky. "
                f"Quiet persistence, Shinkai night interior."
            ),
        ),
        (
            "075",
            "成绩墙光",
            frame(
                f"Students crowd a posted score list in a hallway. Mixed relief and surprise. "
                f"A window at the corridor's end floods the scene with white-gold morning. "
                f"Human drama under too-beautiful light."
            ),
        ),
        (
            "076",
            "看台冰袋",
            frame(
                f"{HARUTO} sits on a bench with a wrapped ankle, teammates around him. "
                f"Ice pack, water bottle, concern. Behind them the empty field and a patient sky. "
                f"Soft, empathetic sports pause."
            ),
        ),
        (
            "077",
            "讲台逆光",
            frame(
                f"{AOI} delivers a student-election speech on the auditorium stage. "
                f"Microphone, a faint projected slide. A high window behind her creates a halo. "
                f"Coming-of-age courage."
            ),
        ),
        (
            "078",
            "镜前西装",
            frame(
                f"Career-center mock interview. {HARUTO} adjusts a borrowed blazer in a tall mirror. "
                f"Resume folder on the table. Through the window, spring clouds. "
                f"The first step out of uniform."
            ),
        ),
        (
            "079",
            "宿舍夜谈",
            frame(
                f"Four roommates in bunks talk with flashlights and snacks after lights-out. "
                f"Fairy lights, posters. A small window shows the moon and thin clouds. "
                f"Intimate, warm, whispered laughter."
            ),
        ),
        (
            "080",
            "晨跑粉空",
            frame(
                f"Students jog the track at sunrise. Breath mist. Pink and gold sky over empty bleachers. "
                f"Tiny figures on a red oval. Healthy, hopeful, the day not yet begun."
            ),
        ),
    ]),
    ("毕业与告别", [
        (
            "081",
            "学位服试穿",
            frame(
                f"Seniors try on black gowns and mortarboards in a classroom. "
                f"{AOI} adjusts her tassel in a window's gold light. Excitement and nerves. "
                f"Outside, a gentle graduation-day sky."
            ),
        ),
        (
            "082",
            "抛帽与云",
            frame(
                f"Graduation caps flying into a bright blue sky above the campus lawn. "
                f"Gowns swirling. The caps are tiny against cathedral clouds. "
                f"Iconic farewell, sky-first composition."
            ),
        ),
        (
            "083",
            "师生台阶",
            frame(
                f"A graduate hugs their homeroom teacher on sunlit stage steps. Diploma tube in hand. "
                f"Tears that still look like light. Families as soft background. "
                f"Afternoon clouds watching quietly."
            ),
        ),
        (
            "084",
            "空教室回望",
            frame(
                f"Empty classroom after the last day. Chairs upturned, chalk tray dusty. "
                f"{AOI} pauses in the doorway, small against a wall of blazing windows. "
                f"Bittersweet silence. The sky pouring in."
            ),
        ),
        (
            "085",
            "校服签名",
            frame(
                f"Friends sign each other's white uniform shirts in the courtyard. "
                f"Colorful markers, inside jokes. Laughter and a few tears. "
                f"Petals or leaves in the air, depending on the season of the heart."
            ),
        ),
        (
            "086",
            "最后一课",
            frame(
                f"Final class ends. The teacher closes the grade book; students stand and applaud. "
                f"Blackboard reads Thank You. Golden afternoon through every window. "
                f"Closure rendered as light."
            ),
        ),
        (
            "087",
            "月台送别",
            frame(
                f"{AOI} waves from a train window; {HARUTO} stands on the platform with a suitcase remaining. "
                f"Summer heat, station signs, a sky too beautiful for goodbye. "
                f"A 5 Centimeters per Second farewell."
            ),
        ),
        (
            "088",
            "相簿与纸箱",
            frame(
                f"Hands flip a printed photo album on a dorm desk among packed boxes. "
                f"Sports days and festivals visible on the pages. "
                f"A window shows moving-out day weather: clear, slightly cruel blue."
            ),
        ),
        (
            "089",
            "钟楼夕阳",
            frame(
                f"Silhouette of the school clock tower against a vast orange sunset. "
                f"{AOI} and {HARUTO} walk away down the central path, almost holding hands, "
                f"tiny under the sky. Timeless ending wide shot."
            ),
        ),
        (
            "090",
            "多年后校门",
            frame(
                f"The same school gate years later, memory-soft light. "
                f"Young adults who look like Aoi and Haruto compare old photos on a phone, "
                f"smiling. Cherry trees, the old sky still doing its work. Nostalgic reunion."
            ),
        ),
    ]),
    ("尾声·天空还在", [
        (
            "091",
            "课桌刻字",
            frame(
                f"Macro of faded initials carved inside a wooden desk lid. Pencil scars, sun stripe on the grain. "
                f"Through the tiny gap of the lid, a slice of classroom window and sky. "
                f"A relic that still holds weather."
            ),
        ),
        (
            "092",
            "跑道球鞋",
            frame(
                f"Worn running shoes on red lane one, a folded relay sash beside them. "
                f"Morning dew. Empty stadium stretching toward a pale enormous sky. "
                f"Quiet athletic poetry."
            ),
        ),
        (
            "093",
            "琴房开窗",
            frame(
                f"Music-room piano with student notes taped inside the lid. Metronome, a forgotten scarf. "
                f"Windows wide open to a sea of afternoon clouds. "
                f"Dust in the light like slow snow."
            ),
        ),
        (
            "094",
            "食堂窗口",
            frame(
                f"A kind cafeteria server hands an extra portion through the steam, smiling. "
                f"Stainless counters. Behind the students, windows full of weather. "
                f"Everyday campus kindness under a beautiful sky."
            ),
        ),
        (
            "095",
            "校门口早安",
            frame(
                f"The school guard greets students at the gate with a small salute. "
                f"Badge glinting. Blooming trees. A morning sky of clean layered clouds. "
                f"A ritual of belonging."
            ),
        ),
        (
            "096",
            "窗台校猫",
            frame(
                f"A calico campus cat sleeps on a sunny windowsill. Students tiptoe past, smiling. "
                f"Ivy, brick, a small food bowl. Beyond the glass: blinding blue and white clouds. "
                f"Gentle mascot moment."
            ),
        ),
        (
            "097",
            "暴雨后的操场",
            frame(
                f"Double rainbow over the sports field after a storm. "
                f"Students point upward, umbrellas folded. Puddles are perfect mirrors. "
                f"Air glittering. Weather as blessing."
            ),
        ),
        (
            "098",
            "萤火虫小径",
            frame(
                f"Summer night path between dormitories. Garden lights, fireflies, slow walkers. "
                f"A deep blue sky with a few bright stars. "
                f"Magical without being fantasy; still a real campus."
            ),
        ),
        (
            "099",
            "黄昏信箱",
            frame(
                f"{HARUTO} drops a handwritten letter into a wooden campus mailbox at dusk. "
                f"Careful fingers. Lantern-colored sky, cicada-season haze. "
                f"A shy confession to the weather itself."
            ),
        ),
        (
            "100",
            "天空还在",
            frame(
                f"Final key visual: the whole friend group on the school steps at golden hour, "
                f"{AOI} and {HARUTO} at the center, arms around shoulders, facing us with bright hopeful smiles. "
                f"Behind them the clock tower and a sky so detailed it could be a painting of heaven. "
                f"Title-card energy. Youth does not end; the sky remains."
            ),
        ),
    ]),
]


def build() -> dict:
    frames = []
    for act_index, (act_title, shots) in enumerate(ACTS, start=1):
        for shot_id, title, text in shots:
            frames.append(
                {
                    "id": shot_id,
                    "act": act_index,
                    "act_title": act_title,
                    "title": title,
                    "text": text,
                }
            )
    if len(frames) != 100:
        raise SystemExit(f"expected 100 frames, got {len(frames)}")
    return {
        "schema": 1,
        "title": "美好的校园时光 · Campus Days",
        "summary": (
            "100-frame FLUX.2 storyboard in a Makoto Shinkai / CoMix Wave Films look: "
            "suburban Japanese high school, Aoi and Haruto, weather as the co-star."
        ),
        "flux2_notes": {
            "language": "English prompts for Mistral TE; UI titles in Chinese.",
            "style": (
                "Locked Shinkai cinematic anime: volumetric clouds, anamorphic flare, "
                "cobalt-to-amber grade, painted backgrounds. Not photoreal live-action."
            ),
            "characters": {
                "Aoi": "16, long black hair, red ribbon, sailor uniform",
                "Haruto": "16, messy dark hair, navy blazer, loosened striped tie",
            },
            "length": "Scene sentence plus a shared style lock; roughly 60–120 words.",
            "workflow": "examples/flux2-dev-t2i.json via catalog flux2-dev on RTX-PRO-6000.",
            "runner": "scripts/run_flux2_campus_storyboard.py",
        },
        "style_lock": STYLE,
        "frames": frames,
    }


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "examples" / "campus-days-storyboard.json"
    payload = build()
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(payload['frames'])} frames)")


if __name__ == "__main__":
    main()
