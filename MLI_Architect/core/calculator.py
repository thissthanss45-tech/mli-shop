from config.loader import ConflictProfile

def calculate_mli(profile: ConflictProfile, scores: dict):
    """
    Принимает профиль (с весами) и оценки от AI (scores).
    Возвращает L, I, R и P_A.
    """
    
    # 1. Считаем L (Средневзвешенное)
    # Формула: Сумма (Балл * Вес) / Сумма Весов
    l_numerator = 0.0
    l_weights_sum = 0.0
    
    for key, weight in profile.weights.L.items():
        score = scores.get(key, 1) # Если AI не дал оценку, считаем 1 (норма)
        l_numerator += score * weight
        l_weights_sum += weight
        
    final_L = l_numerator / l_weights_sum if l_weights_sum > 0 else 1.0

    # 2. Считаем I (Средневзвешенное)
    i_numerator = 0.0
    i_weights_sum = 0.0
    
    for key, weight in profile.weights.I.items():
        score = scores.get(key, 1)
        i_numerator += score * weight
        i_weights_sum += weight
        
    final_I = i_numerator / i_weights_sum if i_weights_sum > 0 else 1.0

    # 3. Считаем R (Риск)
    final_R = final_L * final_I

    return round(final_L, 2), round(final_I, 2), round(final_R, 2)

def get_zone(r_val: float, pa_val: float, profile: ConflictProfile) -> str:
    """Определяет цветовую зону (Зеленая/Красная и т.д.)"""
    
    # ПРАВИЛО 1: Триггер Скорости (P_A)
    # Если скачок резкий, сразу КРАСНЫЙ, плевать на R
    if pa_val >= profile.thresholds.pa_trigger:
        return "🔴 КРАСНЫЙ (ТРИГГЕР P_A)"

    # ПРАВИЛО 2: Пороги R
    if r_val >= profile.thresholds.orange_limit: # >= 15
        return "🔴 КРАСНЫЙ"
    elif r_val >= profile.thresholds.yellow_limit: # >= 12
        return "🟠 ОРАНЖЕВЫЙ"
    elif r_val >= profile.thresholds.green_limit: # >= 9
        return "🟡 ЖЕЛТЫЙ"
    else:
        return "🟢 ЗЕЛЕНЫЙ"