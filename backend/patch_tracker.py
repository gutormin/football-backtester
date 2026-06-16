import codecs

with codecs.open('live_odds_tracker.py', 'r', encoding='utf-8') as f:
    content = f.read()

target1 = '''                        if comp_key not in bookie_entry:
                            bookie_entry[comp_key] = {
                                'market_type': market_key,
                                'outcome_name': outcome_name,
                                'norm_market': norm_market,
                                'opening': price,
                                'current': price,
                                'last_updated': now_str
                            }
                        else:
                            # Update current price
                            if bookie_entry[comp_key]['current'] != price:
                                bookie_entry[comp_key]['current'] = price
                                bookie_entry[comp_key]['last_updated'] = now_str
                                updated_count += 1'''

replacement1 = '''                        if comp_key not in bookie_entry:
                            bookie_entry[comp_key] = {
                                'market_type': market_key,
                                'outcome_name': outcome_name,
                                'norm_market': norm_market,
                                'opening': price,
                                'current': price,
                                'last_updated': now_str,
                                'telegram_sent': False
                            }
                        else:
                            # Update current price
                            if bookie_entry[comp_key]['current'] != price:
                                bookie_entry[comp_key]['current'] = price
                                bookie_entry[comp_key]['last_updated'] = now_str
                                updated_count += 1
                                
                                # Telegram Smart Money Check
                                opening = bookie_entry[comp_key]['opening']
                                if opening > 1.0 and price > 0.0 and price < opening:
                                    drop_pct = ((opening / price) - 1.0) * 100
                                    if drop_pct >= 5.0 and not bookie_entry[comp_key].get('telegram_sent', False):
                                        try:
                                            from backend.telegram_bot import send_telegram_message, format_telegram_smart_money_tip
                                            
                                            commence_time = match_entry.get('commence_time', '')
                                            try:
                                                from datetime import datetime, timezone
                                                dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                                                dt_local = dt.astimezone()
                                                date_str = dt_local.strftime('%d/%m %H:%M')
                                            except:
                                                date_str = commence_time
                                                
                                            msg = format_telegram_smart_money_tip(
                                                match_entry.get('title', 'Desconhecido'),
                                                date_str,
                                                bookie_name,
                                                norm_market.upper(),
                                                opening,
                                                price,
                                                drop_pct
                                            )
                                            send_telegram_message(msg)
                                            bookie_entry[comp_key]['telegram_sent'] = True
                                            print(f"[Live Odds Tracker] Telegram alert sent for {match_entry.get('title')} ({drop_pct:.1f}%)")
                                        except Exception as e:
                                            print(f"[Live Odds Tracker] Erro ao enviar telegram: {e}")'''

if target1 in content:
    content = content.replace(target1, replacement1)
    with codecs.open('live_odds_tracker.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Patched live_odds_tracker.py successfully")
else:
    print("Target1 not found in live_odds_tracker.py")
