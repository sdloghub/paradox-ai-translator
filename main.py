#!/usr/bin/env python3
"""Translate game localisation without changing source files."""
import argparse
import logging
from pathlib import Path
import shutil
import tempfile
import uuid

import paradox

GAMES = ('st', 'hoi4', 'eu4', 'ck3', 'vic3')
ROOT = Path(__file__).resolve().parent


def translate_game(game):
    source = ROOT / 'localisation' / game
    if not source.is_dir():
        raise FileNotFoundError(f'找不到游戏输入目录：{source}')
    output = ROOT / 'chn'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.translation-', dir=output) as directory:
        staging = Path(directory)
        (staging / game).mkdir()
        targets = set()
        failures = 0
        files = sorted(source.rglob('*.yml'))
        if not files:
            logging.warning('%s 没有 yml 文件，保留现有输出', game)
            return False
        for path in files:
            relative = path.relative_to(ROOT / 'localisation')
            target = str(paradox.output_name(relative, game)).casefold()
            if target in targets:
                raise ValueError(f'输出文件名冲突：{relative}')
            targets.add(target)
            logging.info('处理 %s', relative)
            failures += paradox.translate_para(relative, game, staging)
        if failures:
            logging.error('%s 有 %d 条翻译失败，保留原有输出；成功条目已保存到缓存', game, failures)
            return False
        destination = output / game
        backup = output / ('.backup-' + game + '-' + uuid.uuid4().hex)
        had_output = destination.exists()
        if had_output:
            destination.rename(backup)
        try:
            (staging / game).rename(destination)
        except BaseException:
            if had_output:
                backup.rename(destination)
            raise
        if had_output:
            shutil.rmtree(backup)
        logging.info('%s 翻译完成，输出：%s', game, destination)
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description='Paradox Mod 中文翻译工具')
    parser.add_argument('--game', nargs='+', choices=GAMES, help='选择游戏；默认处理所有已存在的游戏目录')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s',
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / 'translation.log', encoding='utf-8')])
    games = args.game or [game for game in GAMES if (ROOT / 'localisation' / game).is_dir()]
    if not games:
        logging.error('localisation 下没有支持的游戏目录')
        return 1
    failed = False
    for game in dict.fromkeys(games):
        try:
            failed = not translate_game(game) or failed
        except Exception as error:
            logging.error('%s 未完成：%s', game, error)
            failed = True
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
