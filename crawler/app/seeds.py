SEED_SITES: dict[str, dict[str, object]] = {
    "www.nankai.edu.cn": {
        "site_name": "南开大学官网",
        "departments": ["南开大学"],
        "audiences": ["本科生", "研究生", "教师", "访客"],
        "seeds": ["https://www.nankai.edu.cn/main.htm"],
    },
    "news.nankai.edu.cn": {
        "site_name": "南开大学新闻网",
        "departments": ["南开大学"],
        "audiences": ["本科生", "研究生", "教师", "访客"],
        "seeds": ["https://news.nankai.edu.cn/"],
    },
    "jwc.nankai.edu.cn": {
        "site_name": "南开大学教务处",
        "departments": ["教务处"],
        "audiences": ["本科生", "教师"],
        "seeds": ["https://jwc.nankai.edu.cn/"],
    },
    "zsb.nankai.edu.cn": {
        "site_name": "南开大学本科招生网",
        "departments": ["本科招生"],
        "audiences": ["本科生", "访客"],
        "seeds": ["https://zsb.nankai.edu.cn/"],
    },
    "yzb.nankai.edu.cn": {
        "site_name": "南开大学研究生招生网",
        "departments": ["研究生招生"],
        "audiences": ["研究生", "访客"],
        "seeds": ["https://yzb.nankai.edu.cn/"],
    },
    "graduate.nankai.edu.cn": {
        "site_name": "南开大学研究生院",
        "departments": ["研究生院"],
        "audiences": ["研究生", "教师"],
        "seeds": ["https://graduate.nankai.edu.cn/"],
    },
    "cc.nankai.edu.cn": {
        "site_name": "南开大学计算机学院",
        "departments": ["计算机学院", "计算机科学与技术"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://cc.nankai.edu.cn/"],
    },
    "cyber.nankai.edu.cn": {
        "site_name": "南开大学网络与空间安全学院",
        "departments": ["网络与空间安全学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://cyber.nankai.edu.cn/"],
    },
    "ai.nankai.edu.cn": {
        "site_name": "南开大学人工智能学院",
        "departments": ["人工智能学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://ai.nankai.edu.cn/"],
    },
    "env.nankai.edu.cn": {
        "site_name": "南开大学环境学院",
        "departments": ["环境学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://env.nankai.edu.cn/"],
    },
    "bs.nankai.edu.cn": {
        "site_name": "南开大学商学院",
        "departments": ["商学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://bs.nankai.edu.cn/"],
    },
    "economics.nankai.edu.cn": {
        "site_name": "南开大学经济学院",
        "departments": ["经济学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://economics.nankai.edu.cn/"],
    },
    "finance.nankai.edu.cn": {
        "site_name": "南开大学金融学院",
        "departments": ["金融学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://finance.nankai.edu.cn/"],
    },
    "chem.nankai.edu.cn": {
        "site_name": "南开大学化学学院",
        "departments": ["化学学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://chem.nankai.edu.cn/"],
    },
    "medical.nankai.edu.cn": {
        "site_name": "南开大学医学院",
        "departments": ["医学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://medical.nankai.edu.cn/"],
    },
    "physics.nankai.edu.cn": {
        "site_name": "南开大学物理科学学院",
        "departments": ["物理科学学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://physics.nankai.edu.cn/"],
    },
    "math.nankai.edu.cn": {
        "site_name": "南开大学数学科学学院",
        "departments": ["数学科学学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://math.nankai.edu.cn/"],
    },
    "cz.nankai.edu.cn": {
        "site_name": "南开大学马克思主义学院",
        "departments": ["马克思主义学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://cz.nankai.edu.cn/"],
    },
    "zfxy.nankai.edu.cn": {
        "site_name": "南开大学周恩来政府管理学院",
        "departments": ["周恩来政府管理学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://zfxy.nankai.edu.cn/"],
    },
    "shxy.nankai.edu.cn": {
        "site_name": "南开大学社会学院",
        "departments": ["社会学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://shxy.nankai.edu.cn/"],
    },
    "ceo.nankai.edu.cn": {
        "site_name": "南开大学电子信息与光学工程学院",
        "departments": ["电子信息与光学工程学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://ceo.nankai.edu.cn/"],
    },
    "sky.nankai.edu.cn": {
        "site_name": "南开大学生命科学学院",
        "departments": ["生命科学学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://sky.nankai.edu.cn/"],
    },
    "sfs.nankai.edu.cn": {
        "site_name": "南开大学外国语学院",
        "departments": ["外国语学院"],
        "audiences": ["本科生", "研究生", "教师"],
        "seeds": ["https://sfs.nankai.edu.cn/"],
    },
}


ALLOWED_HOSTS = set(SEED_SITES.keys())

