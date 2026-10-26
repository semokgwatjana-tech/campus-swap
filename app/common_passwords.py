"""Passwords and bases that are far too common to accept. Kept short on purpose:
the length rule already blocks anything under 10 characters."""

COMMON_PASSWORDS = frozenset("""
1234567890 0123456789 0987654321 1234567891 123456789a a123456789 1q2w3e4r5t 1qaz2wsx3e 1q2w3e4r5t6y
qwertyuiop qwerty1234 qwerty12345 qwerty123456 qwertyuiop1 asdfghjkl1 asdfghjklz zxcvbnm123 zxcvbnmasd
abcdefghij abcdefghi1 abcd123456 abc1234567 password12 password123 password1234 password12345 password123!
passw0rd123 p@ssw0rd123 p@ssword12 pass123456 passwordpassword letmein123 letmein1234 welcome123 welcome1234
welcome12345 iloveyou12 iloveyou123 iloveyou1234 football123 football1234 baseball123 basketball1 superman123
batman12345 sunshine123 princess123 princess1234 monkey1234 monkey12345 dragon12345 master12345 shadow12345
trustno1234 changeme123 changeme1234 administrator admin12345 admin123456 administrator1 campusswap campusswap1
campusswap12 campusswap123 campusswap1234 campus12345 student1234 student12345 studentlife university1
university12 university123 mypassword1 mypassword12 mypassword123 starwars123 whatever123 freedom1234
johannesburg pretoria123 capetown123 durban12345 soweto12345 mzansi12345 southafrica springbok123 kaizerchiefs
orlandopirates thankyou123 blessed1234 godislove123 jesus123456 loveyou1234 iloveyou2 0000000000 1111111111
2222222222 1212121212 1231231234 9876543210 1357924680 2468013579 11111111111 00000000000 qazwsxedc123 zaq12wsxcde
""".split())

# The core word of a password once trailing digits/symbols and look-alike
# characters (@ for a, 0 for o, $ for s, 3 for e...) are stripped.
COMMON_BASES = frozenset("""
password passwort welcome qwerty qwertyuiop letmein iloveyou football baseball basketball superman batman
sunshine princess monkey dragon master shadow trustno admin administrator changeme student campusswap campus
university freedom whatever starwars hello secret login computer internet michael jordan liverpool chelsea
arsenal manutd kaizerchiefs chiefs pirates springbok springboks mzansi johannesburg capetown soweto pretoria
durban southafrica thankyou blessed godislove loveyou mypassword passcode abcdefg abcdefgh asdfghjkl zxcvbnm
iloveu mustang cheese hunter ranger pepper cookie summer winter spring autumn flower
""".split())
