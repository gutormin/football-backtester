import codecs

func = """
window.selectAllLeagues = function(check) {
    document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]').forEach(cb => {
        cb.checked = check;
    });
};
"""

with codecs.open('app.js', 'a', encoding='utf-8') as f:
    f.write(func)

print("Function appended.")
