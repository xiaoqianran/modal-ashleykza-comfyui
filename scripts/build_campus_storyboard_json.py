#!/usr/bin/env python3
"""Build examples/campus-days-storyboard.json (100 FLUX.2 frames)."""

from __future__ import annotations

import json
from pathlib import Path

# FLUX.2: natural-language sentences; subject → action → style → environment → lens/light.
# No comma-tag stacks; positive wording only; ~30–80 words per frame.

ACTS = [
    ("开学清晨", [
        (
            "001",
            "校门晨曦",
            "A wide establishing shot of an East Asian university gate at dawn, pale gold sunlight cutting through morning mist, "
            "fresh green plane trees lining the stone path, a few students in navy blazers walking uphill with backpacks, "
            "soft cinematic lighting, photorealistic, 24mm landscape still.",
        ),
        (
            "002",
            "单车入校",
            "A teenage boy in a white shirt and navy blazer rides a bicycle through the open campus gate, "
            "wind lifting his tie slightly, cherry blossom petals drifting across the frame, "
            "warm side light, documentary photography, 35mm film still, sharp focus.",
        ),
        (
            "003",
            "樱花大道",
            "Two friends, a girl and a boy in matching school uniforms, walk together under blooming cherry trees on campus, "
            "pink petals falling like snow, they laugh while holding iced coffee cups, "
            "shallow depth of field, golden morning glow, photorealistic editorial portrait.",
        ),
        (
            "004",
            "公告栏前",
            "Close-up of a campus bulletin board covered with club flyers and exam schedules, "
            "a girl with a ponytail pins a handwritten note while classmates gather behind her, "
            "natural daylight, fine paper texture, 50mm street photography, photorealistic.",
        ),
        (
            "005",
            "教学楼台阶",
            "Low-angle view of wide stone steps leading to a red-brick academic building, "
            "students climbing in small groups, long shadows stretching across the stairs, "
            "clear blue sky, cinematic composition, photorealistic campus life scene.",
        ),
        (
            "006",
            "新生问路",
            "A nervous freshman with an oversized backpack asks directions from an upperclassman near a campus map sign, "
            "both smiling gently, ivy climbing the wall behind them, soft overcast light, "
            "intimate human moment, 85mm portrait, photorealistic.",
        ),
        (
            "007",
            "铃声响起",
            "Interior hallway of a school building as the first bell rings, "
            "classroom doors opening and students pouring into the corridor with books and tablets, "
            "motion blur at the edges, bright fluorescent mixed with window light, photorealistic.",
        ),
        (
            "008",
            "教室窗景",
            "View from inside a sunlit classroom looking out through tall windows at the green campus quad, "
            "desks neatly arranged, chalk dust floating in a sunbeam, quiet anticipation before class, "
            "still life atmosphere, 35mm, photorealistic.",
        ),
        (
            "009",
            "同桌微笑",
            "Two desk mates, a girl and a boy, share a shy smile across a wooden classroom desk, "
            "open textbooks and color highlighters between them, afternoon light on their faces, "
            "gentle teenage romance mood, 85mm shallow focus, photorealistic.",
        ),
        (
            "010",
            "班主任点名",
            "A kind middle-aged teacher stands at the front of a classroom calling roll from a clipboard, "
            "rows of uniformed students sit attentively, blackboard reads Welcome New Semester in chalk, "
            "balanced classroom lighting, photorealistic documentary style.",
        ),
    ]),
    ("课堂时光", [
        (
            "011",
            "数学板书",
            "A teacher writes elegant geometry proofs on a green blackboard while students take notes, "
            "white chalk lines crisp against the dark board, sunlight stripes across the back row, "
            "academic atmosphere, 50mm classroom photography, photorealistic.",
        ),
        (
            "012",
            "认真听讲",
            "Close portrait of a focused girl listening in class, chin resting on her hand, "
            "eyes bright with curiosity, blurred classmates behind her, window light on one cheek, "
            "editorial student portrait, 85mm, photorealistic.",
        ),
        (
            "013",
            "传纸条",
            "A playful moment as a folded note passes secretly between desks during a lecture, "
            "only hands and uniform sleeves visible, teacher blurred at the front, "
            "candid school memory, warm tones, 35mm film still, photorealistic.",
        ),
        (
            "014",
            "英语朗读",
            "Students stand in turn reading English aloud from textbooks, "
            "a boy at the podium speaks confidently while others follow along, "
            "classroom flags and vocabulary posters on the wall, natural light, photorealistic.",
        ),
        (
            "015",
            "化学实验",
            "High school chemistry lab with students in safety goggles watching a gentle blue flame, "
            "glass beakers and periodic table chart behind them, cool lab light mixed with warm window glow, "
            "science education scene, sharp detail, photorealistic.",
        ),
        (
            "016",
            "显微镜下",
            "A girl peers into a microscope while her lab partner sketches observations in a notebook, "
            "specimen slides and stainless steel benches around them, concentrated expressions, "
            "macro documentary style, photorealistic.",
        ),
        (
            "017",
            "美术素描",
            "Art classroom with students drawing still-life vases on easels, "
            "charcoal smudges on fingers, north-facing skylight giving soft even illumination, "
            "creative campus afternoon, fine art photography, photorealistic.",
        ),
        (
            "018",
            "音乐教室",
            "A student plays piano near open windows while others tune violins in a music room, "
            "sheet music scattered on stands, late afternoon light painting the wooden floor gold, "
            "romantic school club mood, 35mm, photorealistic.",
        ),
        (
            "019",
            "体育课集合",
            "PE teacher blows a whistle on a green athletic field as students line up in gym uniforms, "
            "white running shoes on red track lanes, distant bleachers and goal posts, "
            "bright midday sun, sports documentary photography, photorealistic.",
        ),
        (
            "020",
            "课间走廊",
            "Crowded hallway between classes, friends leaning against lockers trading snacks and stories, "
            "posters for the autumn festival on the walls, lively youthful energy, "
            "handheld street style, 28mm, photorealistic.",
        ),
    ]),
    ("午间与操场", [
        (
            "021",
            "食堂排队",
            "Students queue with trays in a bright campus cafeteria, steam rising from noodle stations, "
            "overhead menus in Chinese and English, friendly chatter filling the space, "
            "wide interior shot, photorealistic food court atmosphere.",
        ),
        (
            "022",
            "分享午餐",
            "Four friends share lunch at a cafeteria table, swapping side dishes and laughing, "
            "rice bowls, soup cups, and fruit on plastic trays, warm indoor lighting, "
            "slice-of-life photography, 50mm, photorealistic.",
        ),
        (
            "023",
            "窗边独坐",
            "A quiet boy eats alone by a tall cafeteria window overlooking the sports field, "
            "headphones around his neck, sketchbook open beside his tray, thoughtful mood, "
            "soft backlight, cinematic solitude, photorealistic.",
        ),
        (
            "024",
            "小卖部冰饮",
            "After lunch rush at a campus convenience shop, students buy iced lemon tea and ice cream bars, "
            "glass-door refrigerators glowing cool blue, coins and student cards on the counter, "
            "vivid color, documentary retail scene, photorealistic.",
        ),
        (
            "025",
            "操场散步",
            "Two girls walk the rubber track slowly after lunch, uniforms loosened, hair ribbons fluttering, "
            "cloud shadows moving across the field, distant students playing soccer, "
            "peaceful campus afternoon, 35mm, photorealistic.",
        ),
        (
            "026",
            "篮球三分",
            "A boy leaps for a three-point shot on an outdoor basketball court, ball frozen mid-air, "
            "friends watching from the sideline, afternoon sun flaring behind the hoop, "
            "dynamic sports photography, 70mm, photorealistic.",
        ),
        (
            "027",
            "足球传球",
            "Students play casual soccer on a green campus pitch, one player passes through defenders, "
            "cleats kicking up grass, goal net and school building in background, "
            "action freeze, telephoto sports still, photorealistic.",
        ),
        (
            "028",
            "看台加油",
            "Cheerful classmates sit on metal bleachers clapping for a relay race, "
            "homemade banners and bottled water around them, blue sky and white clouds above, "
            "youthful team spirit, wide shot, photorealistic.",
        ),
        (
            "029",
            "跑道冲刺",
            "Final sprint of a school track race, two runners neck and neck, faces strained with effort, "
            "red lane markers sharp beneath their feet, crowd blur in background, "
            "high-speed sports capture, photorealistic.",
        ),
        (
            "030",
            "树荫小憩",
            "Friends nap and study under a large campus oak tree, textbooks as pillows, dappled shade on faces, "
            "a gentle breeze moving leaves, lazy golden hour approaching, "
            "pastoral school memory, 50mm, photorealistic.",
        ),
    ]),
    ("图书馆与社团", [
        (
            "031",
            "图书馆入口",
            "Grand wooden doors of a university library open to a quiet reading hall, "
            "students ascending marble steps with laptops and stacks of books, reverent atmosphere, "
            "symmetrical architecture, soft ambient light, photorealistic.",
        ),
        (
            "032",
            "书架寻书",
            "A girl on tiptoe reaches for a novel on a tall library shelf, "
            "sunbeams through tall windows illuminating dust motes, rows of colorful spines, "
            "quiet scholarly mood, 35mm, photorealistic.",
        ),
        (
            "033",
            "自习长桌",
            "Long study tables in the library filled with students preparing for exams, "
            "lamps, highlighted notes, and coffee cups, focused silence, evening blue outside windows, "
            "academic diligence scene, photorealistic.",
        ),
        (
            "034",
            "双人复习",
            "A boy and girl quiz each other with flashcards in a library corner, "
            "whispering and smiling when an answer is right, stacked textbooks between them, "
            "intimate study partnership, shallow depth of field, photorealistic.",
        ),
        (
            "035",
            "摄影社外拍",
            "Campus photography club on the lawn, one student frames a shot with a DSLR while others pose playfully, "
            "camera straps and light reflectors on the grass, creative youth energy, "
            "meta photography scene, 50mm, photorealistic.",
        ),
        (
            "036",
            "戏剧排练",
            "Drama club rehearses on a small auditorium stage, students in simple costumes reading scripts, "
            "spotlight warming the wooden floor, empty seats in darkness beyond, "
            "theatrical school life, cinematic contrast, photorealistic.",
        ),
        (
            "037",
            "街舞社团",
            "Dance club practices hip-hop moves in a mirrored studio after school, "
            "sneakers squeaking on polished floor, urban posters on the wall, energetic poses reflected, "
            "dynamic youth culture, wide angle, photorealistic.",
        ),
        (
            "038",
            "天文台夜",
            "A small campus observatory dome opens at dusk as astronomy club members align a telescope, "
            "violet sky fading to stars, silhouettes of excited students, "
            "science wonder mood, long exposure feel, photorealistic.",
        ),
        (
            "039",
            "志愿者义卖",
            "Charity bake sale tables on the campus lawn, students in club aprons sell cupcakes and handmade crafts, "
            "colorful bunting between trees, smiling customers with paper bags, "
            "community warmth, documentary style, photorealistic.",
        ),
        (
            "040",
            "广播站午后",
            "Two students host the school radio show in a tiny broadcast booth, "
            "microphones, mixing board lights, playlist notes on the desk, song request slips pinned nearby, "
            "cozy media nook, warm tungsten light, photorealistic.",
        ),
    ]),
    ("四季校园", [
        (
            "041",
            "春雨操场",
            "Light spring rain dots the empty running track, a girl walks alone with a clear umbrella, "
            "puddles mirror red track lanes and gray sky, fresh green buds on nearby trees, "
            "melancholy beauty, 35mm rainy day photography, photorealistic.",
        ),
        (
            "042",
            "初夏林荫",
            "Bright early summer on campus, students in short-sleeve uniforms eat watermelon under plane trees, "
            "strong green canopy, cicada-season heat haze in the distance, "
            "vivid seasonal slice of life, photorealistic.",
        ),
        (
            "043",
            "荷塘月色",
            "Evening by a campus pond with lotus leaves, friends sit on a wooden bridge sharing earphones, "
            "moon reflection rippling on dark water, fireflies hinted near the reeds, "
            "poetic night scene, soft blue hour, photorealistic.",
        ),
        (
            "044",
            "银杏大道",
            "Autumn campus avenue covered in golden ginkgo leaves, students kick piles of leaves while walking to class, "
            "warm amber sunlight filtering through yellow crowns, nostalgic fall mood, "
            "seasonal landscape photography, photorealistic.",
        ),
        (
            "045",
            "秋日读书",
            "A boy reads on a bench surrounded by fallen maple leaves, scarf loose around his neck, "
            "hot tea steam rising from a thermos beside him, quiet contemplation, "
            "portrait with bokeh leaves, 85mm, photorealistic.",
        ),
        (
            "046",
            "初雪教学楼",
            "First snow dusts the red-brick classroom building and bare branches, "
            "students in coats photograph the scene with phones, breath visible in cold air, "
            "winter campus hush, crisp daylight, photorealistic.",
        ),
        (
            "047",
            "雪地雪人",
            "Friends build a small snowman on the campus quad, scarves and mittens colorful against white snow, "
            "laughter and flying snowballs in soft focus background, playful winter memory, "
            "bright overcast light, photorealistic.",
        ),
        (
            "048",
            "冬日窗暖",
            "Inside a heated classroom while snow falls outside tall windows, "
            "students cup warm mugs during a break, condensation on the glass, cozy contrast, "
            "intimate indoor winter scene, photorealistic.",
        ),
        (
            "049",
            "春日返校",
            "Spring semester return, cherry blossoms fuller than before, old friends reunite with hugs near the gate, "
            "luggage and blooming trees framing the embrace, renewal and joy, "
            "emotional reunion portrait, 50mm, photorealistic.",
        ),
        (
            "050",
            "夏至黄昏",
            "Long summer twilight over the campus clock tower, sky gradient from orange to indigo, "
            "silhouettes of graduates tossing caps in rehearsal on the lawn below, "
            "epic golden hour wide shot, photorealistic.",
        ),
    ]),
    ("青春与友谊", [
        (
            "051",
            "天台吹风",
            "Three friends sit on a rooftop ledge safe behind a fence, legs dangling, city and campus spread below, "
            "wind tousling their hair, sharing chips and secrets at sunset, "
            "youthful freedom mood, cinematic backlit portrait, photorealistic.",
        ),
        (
            "052",
            "生日惊喜",
            "Classmates surprise a girl with a small birthday cake in the homeroom after final period, "
            "candles glowing, handmade banner and phone flashlights, her hands covering happy tears, "
            "warm celebration scene, photorealistic.",
        ),
        (
            "053",
            "雨中共伞",
            "A boy quietly holds an umbrella over a girl as they cross a rainy campus courtyard, "
            "their shoulders almost touching, reflections on wet stone, soft gray rain light, "
            "tender teenage romance, 50mm, photorealistic.",
        ),
        (
            "054",
            "单车后座",
            "A girl rides on the back rack of a bicycle along a tree-lined campus road at dusk, "
            "arms spread for balance, both laughing, long shadows on the pavement, "
            "carefree motion blur at edges, photorealistic.",
        ),
        (
            "055",
            "考试加油",
            "Before a major exam, friends form a circle in the hallway doing a team cheer, "
            "hands stacked in the center, determined smiles, backpacks at their feet, "
            "motivational school moment, documentary style, photorealistic.",
        ),
        (
            "056",
            "深夜便利店",
            "Two students in hoodies buy instant noodles at a 24-hour shop near campus after study group, "
            "fluorescent glow, rain on the glass door, tired but happy faces, "
            "urban night slice of life, photorealistic.",
        ),
        (
            "057",
            "吉他草坪",
            "A boy plays acoustic guitar on the campus lawn at golden hour while friends sing along softly, "
            "sheet music weighted by stones, distant frisbee players blurred, "
            "music friendship scene, warm lens flare, photorealistic.",
        ),
        (
            "058",
            "胶片合影",
            "A group of six friends squeeze into a self-timer photo on stone steps, "
            "someone runs into frame at the last second, imperfect genuine smiles, vintage film color grade, "
            "nostalgic student album aesthetic, photorealistic.",
        ),
        (
            "059",
            "争吵和解",
            "Two close friends sit on playground bleachers after a quarrel, one offers a soda as peace, "
            "awkward half-smiles turning into relief, late afternoon empty field behind them, "
            "emotional honesty, intimate 85mm portrait, photorealistic.",
        ),
        (
            "060",
            "毕业墙留言",
            "Students write messages and signatures on a temporary graduation memory wall on campus, "
            "colorful markers, polaroids taped among the notes, hands layering new wishes, "
            "bittersweet farewell texture, close documentary shot, photorealistic.",
        ),
    ]),
    ("节庆与比赛", [
        (
            "061",
            "校园文化节",
            "Outdoor cultural festival on the main quad, booths with calligraphy, dance, and robotics demos, "
            "paper lanterns strung between trees, crowds in festive mood, "
            "vibrant campus carnival, wide establishing shot, photorealistic.",
        ),
        (
            "062",
            "汉服走秀",
            "Students in elegant hanfu walk a simple runway on the lawn during culture day, "
            "bamboo fans and embroidered sleeves moving gracefully, audience clapping under parasols, "
            "traditional meets youth, fashion show photography, photorealistic.",
        ),
        (
            "063",
            "辩论赛",
            "Intense high school debate in a lecture hall, two teams at opposing podiums, "
            "timers and water bottles on the table, audience leaning forward, spotlight on speakers, "
            "intellectual competition scene, photorealistic.",
        ),
        (
            "064",
            "合唱比赛",
            "School choir in matching uniforms performs on stage, mouths open in harmony, "
            "conductor's hands raised, parents recording from the dark auditorium, "
            "uplifting performance moment, stage lighting, photorealistic.",
        ),
        (
            "065",
            "科技展机器人",
            "Robotics club displays a small wheeled robot navigating cones in the science building atrium, "
            "curious younger students watch, LED status lights blinking, banners for STEM week, "
            "future-facing campus event, sharp detail, photorealistic.",
        ),
        (
            "066",
            "校园马拉松",
            "Charity campus marathon with numbered bibs, runners passing a water station near the lake, "
            "volunteers handing cups, colorful flags marking the route, energetic community scene, "
            "sports event photography, photorealistic.",
        ),
        (
            "067",
            "露天电影",
            "Night outdoor movie on the athletic field, students on blankets and folding chairs facing a large screen, "
            "projector beam cutting through faint mist, stars above, shared popcorn, "
            "romantic campus cinema, photorealistic.",
        ),
        (
            "068",
            "中秋灯笼",
            "Mid-autumn evening on campus with paper lanterns glowing along a path, "
            "students share mooncakes on a stone table, full moon rising behind the library dome, "
            "festival warmth, soft lantern light, photorealistic.",
        ),
        (
            "069",
            "圣诞装饰",
            "Student council hangs lights and paper snowflakes in the main hallway before winter break, "
            "ladder, tape, and laughter, mixed holiday and exam-week chaos, cozy institutional charm, "
            "documentary interior, photorealistic.",
        ),
        (
            "070",
            "新年倒计时",
            "Friends on the dorm rooftop count down to the new year with sparklers, city lights below, "
            "breath in cold air, scarves and puffer jackets, joy and hope on their faces, "
            "celebratory night portrait, photorealistic.",
        ),
    ]),
    ("备考与成长", [
        (
            "071",
            "模考清晨",
            "Early morning before mock exams, a girl reviews notes under a desk lamp in the dorm, "
            "alarm clock, stacked past papers, pale dawn through curtains, determined calm, "
            "study grind portrait, photorealistic.",
        ),
        (
            "072",
            "错题本",
            "Close-up of hands rewriting math mistakes in a neat error notebook, "
            "red pen corrections, ruler and eraser crumbs, textbook open beside, "
            "academic discipline detail shot, photorealistic.",
        ),
        (
            "073",
            "老师答疑",
            "After class, a teacher patiently explains a physics problem at the podium while two students listen closely, "
            "emptying classroom, late sun through windows, mentorship warmth, "
            "educational documentary, 50mm, photorealistic.",
        ),
        (
            "074",
            "通宵自习室",
            "Late night in a 24-hour study room, few students remain with coffee and dim desk lamps, "
            "city glow outside floor-to-ceiling glass, quiet exhaustion and persistence, "
            "noir academic mood, photorealistic.",
        ),
        (
            "075",
            "成绩公布",
            "Students crowd a posted score list on a hallway board, mixed reactions of relief and surprise, "
            "fingers pointing at names, phones photographing results, tense human drama, "
            "candid school journalism style, photorealistic.",
        ),
        (
            "076",
            "运动受伤",
            "A boy sits on the bench with a wrapped ankle while teammates and the nurse comfort him, "
            "ice pack and water bottle nearby, concern and solidarity on faces, "
            "empathetic sports moment, photorealistic.",
        ),
        (
            "077",
            "演讲比赛",
            "A girl delivers a speech on auditorium stage for a student election, "
            "confident posture, microphone, projected slide behind her, peers watching attentively, "
            "leadership coming of age, stage photography, photorealistic.",
        ),
        (
            "078",
            "实习西装",
            "Senior students practice job interviews in career center mock rooms, "
            "one adjusts a borrowed blazer in a mirror, resume folders on the table, "
            "transition to adulthood, clean office light, photorealistic.",
        ),
        (
            "079",
            "宿舍夜谈",
            "Four roommates in bunk beds talk softly with flashlights and snacks after lights-out, "
            "posters and fairy lights on walls, whispered laughter, intimate dorm night, "
            "low-key warm photography, photorealistic.",
        ),
        (
            "080",
            "清晨跑步",
            "Disciplined students jog around the track at sunrise before class, "
            "breath mist in cool air, rhythmic footsteps, pink sky over empty bleachers, "
            "healthy routine scene, wide landscape, photorealistic.",
        ),
    ]),
    ("毕业与告别", [
        (
            "081",
            "学位服试穿",
            "Graduating seniors try on black gowns and mortarboards in a classroom, "
            "adjusting tassels and taking mirror selfies, excitement and nervousness, "
            "pre-commencement joy, natural light, photorealistic.",
        ),
        (
            "082",
            "抛帽瞬间",
            "Frozen moment of graduation caps flying into a bright blue sky above the campus lawn, "
            "gowns swirling, arms raised, crowd cheering below, iconic farewell image, "
            "high shutter speed celebration, photorealistic.",
        ),
        (
            "083",
            "师生拥抱",
            "A graduate hugs their homeroom teacher on stage steps after the ceremony, "
            "diploma tube in hand, tears and smiles, families blurred in background, "
            "emotional gratitude portrait, 85mm, photorealistic.",
        ),
        (
            "084",
            "空教室回望",
            "An empty classroom after the last day, chairs upturned on desks, sunlight on dusty chalk tray, "
            "a lone graduate pauses in the doorway looking back, bittersweet silence, "
            "cinematic farewell still, photorealistic.",
        ),
        (
            "085",
            "校服签名",
            "Friends sign each other's white uniform shirts with colorful markers in the courtyard, "
            "inside jokes and names covering the fabric, laughter and a few tears, "
            "youth ritual close-up, photorealistic.",
        ),
        (
            "086",
            "最后一堂课",
            "Final class ends as the teacher closes the grade book and students applaud standing, "
            "blackboard message reads Thank You, golden afternoon through windows, "
            "closure and gratitude, classroom documentary, photorealistic.",
        ),
        (
            "087",
            "火车站送别",
            "At the campus-town train station, friends wave as one boards with a suitcase for university elsewhere, "
            "platform signs, late summer heat, mixed joy and separation, "
            "travel farewell scene, 35mm, photorealistic.",
        ),
        (
            "088",
            "相册翻阅",
            "Hands flip through a printed photo album on a dorm desk, images of sports days and festivals visible, "
            "string lights and packed boxes nearby, moving-out day nostalgia, "
            "tactile memory detail, photorealistic.",
        ),
        (
            "089",
            "钟楼夕阳",
            "Silhouette of the campus clock tower against a vast orange sunset, "
            "two graduates walk away down the central path hand in hand, long shadows, "
            "timeless romantic ending wide shot, photorealistic.",
        ),
        (
            "090",
            "十年之约",
            "Epilogue mood: the same campus gate years later in soft memory-like light, "
            "young alumni return with coffee, comparing old photos on a phone, smiles of recognition, "
            "nostalgic reunion tone, gentle film grain, photorealistic.",
        ),
    ]),
    ("尾声·珍藏时光", [
        (
            "091",
            "课桌刻字",
            "Macro detail of faded initials carved inside a wooden desk lid, "
            "pencil scratches and old gum stains telling silent stories, sun stripe across the grain, "
            "intimate school relic, photorealistic.",
        ),
        (
            "092",
            "球鞋与跑道",
            "Worn running shoes rest on red track lane one beside a folded relay sash, "
            "morning dew on the rubber surface, empty stadium stretching ahead, "
            "quiet athletic poetry, low angle, photorealistic.",
        ),
        (
            "093",
            "琴房留言",
            "A music room piano with student messages taped inside the lid, "
            "metronome and forgotten scarf on the bench, afternoon dust in light beams, "
            "sentimental still life, photorealistic.",
        ),
        (
            "094",
            "食堂阿姨",
            "Warm portrait of a cafeteria auntie serving an extra portion with a kind smile, "
            "steam, stainless counters, students waiting patiently behind, everyday campus kindness, "
            "documentary portrait, 50mm, photorealistic.",
        ),
        (
            "095",
            "保安敬礼",
            "Campus security guard greets students at the gate with a friendly morning salute, "
            "badge gleaming, blooming trees framing the routine ritual, sense of safety and belonging, "
            "community portrait, photorealistic.",
        ),
        (
            "096",
            "流浪猫学长",
            "A calico campus cat naps on a sunny windowsill while students tiptoe past smiling, "
            "small bowl of food below, ivy and brick texture, whimsical school mascot moment, "
            "gentle humor, photorealistic.",
        ),
        (
            "097",
            "雨后彩虹",
            "Double rainbow arches over the campus sports field after a storm, "
            "students point upward with umbrellas folded, puddles reflecting vivid color, "
            "hopeful cinematic sky, wide landscape, photorealistic.",
        ),
        (
            "098",
            "萤火虫步道",
            "Summer night path between dormitories lined with soft garden lights and fireflies, "
            "couples and friends stroll slowly, crickets implied in the warm dark, "
            "magical campus evening, long exposure feel, photorealistic.",
        ),
        (
            "099",
            "信箱情书",
            "A shy student drops a handwritten letter into a campus wooden suggestion mailbox at dusk, "
            "heart pounding implied in careful fingers, lantern light and cicada season, "
            "tender secret romance, close shot, photorealistic.",
        ),
        (
            "100",
            "青春不散场",
            "Final panoramic tableau of the whole friend group on the school steps at golden hour, "
            "arms around shoulders, uniforms and graduation scarves mixed, facing the camera with bright hopeful smiles, "
            "title-card energy, epic 24mm group portrait, photorealistic.",
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
        "summary": "100-frame FLUX.2 storyboard: arrival, classes, sports, library, seasons, friendship, festivals, exams, graduation.",
        "flux2_notes": {
            "language": "English prompts for Mistral TE; UI titles in Chinese.",
            "style": "Natural full sentences; subject first; positive wording; no negative prompt.",
            "length": "Roughly 30–80 words per frame.",
            "workflow": "examples/flux2-dev-t2i.json via catalog flux2-dev on RTX-PRO-6000.",
            "runner": "scripts/run_flux2_campus_storyboard.py",
        },
        "frames": frames,
    }


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "examples" / "campus-days-storyboard.json"
    payload = build()
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(payload['frames'])} frames)")


if __name__ == "__main__":
    main()
