"""An API to communicate with the Lutron Caseta Smart Bridge."""

# This is the private key for the Lutron Smart Bridge 'leap' user.
# https://github.com/njschwartz/Lutron-Smart-Pi/blob/master/RaspberryPi/LutronPi.py

_LUTRON_SSH_KEY = """\
-----BEGIN RSA PRIVATE KEY-----
MIIEogIBAAKCAQEApX6g2uGLyC8ZDw13Vvn/lgp4pf5BrEy2oZf+yFouGOn+UI+J
7d9yWWrP8nUJXIzz1YQ3Fs4YgDFus5bu1g/3XuK3J7kk5lVuz3wTgqDGw2jIP3mb
IUIlonEvJp+5aKNjMUkFGHkWo6nlqXx0nQjFrqhU1bZTPKwKON35IrauqmQaI+z7
pA2DEW1w2a/sO+Y4t/iBzTU0U4M9C/5PcT5GRtfb23RFP5NaiE38OC68rWfqFR91
+37smywvX1vaxhVbP5DkZXtZNBDK5jXtQ3j0dHwnKSyu7JDmhhq/pHgMEZaxtAjE
ziFJdP56P8Hy0TdXcvG/Wfw+F94KltOsp/wJfQIDAQABAoIBABvlX2nl0PEad0fh
RjeEBoAdHb8lP56yg6pze3/8K38JmlOsDlzpaFYIOistbTmLjOJ12e9fKCQbsQRW
scWlhVYaMzNf8wdcaURSLtu7DCYOOIryjaKqirt6Bq+lBtTLjcHWBCTe7GEEF3Fd
SC7cNq49M6eehyNYAJUbXY5rar/PwEpKFE/5LuTP4xXjJCvCsMffcenBj/rZp7g8
nigZ4pboNJNY7ODpTg4J2tk6x5HPSoYr9aM8CL4IjG4pcoJe8ROXm5YM+JQSwL1d
nUH4SA4qQOpE3cHLtxfmAoJ8vwu7tIpxD5YMMAACg1dVZGPgVVSOlTXH9jxC2vfn
GVQa98ECgYEA27HMMeWPFbgVuscR6cVmCriAuKlhYvJJkhYFjJV8qWMvgwsjOdl6
O1wGzW4IWSzzSoz0MdBs1ikUj1FlfriGpRWBQkT7rdIGwbKus3BXSIt52b/3cCvx
2H1qS/P9gAW8yfw6LcIGA9L26BOWCDqtmMX1aJ/zkVdrafr7AOIf+w0CgYEAwNfm
AW3oSald1NpG1CoB6rA7VJg9ulXm2t0Ha8czQ483pFjkDaaETQyIO+dtTg1sqrbO
dcFn+FF66fBlQN/ZNGb9+IbGSdITkI5iV5D1RSXJVuxaZFkX6IZPwwBgL6ouBPW2
lNfg06j4RKj32fddPxtjJIwTkOo6VUbSCbbh7DECgYBjDuIRRX6kvmId25C6JWWD
Q/nWSZk9sh12HzPVVbnl7nEH10fE18iDZ1Ux34EoJFp2rOOWanIIhnFcxcjLwIwF
d5LWvJ/2mhKt19Fp2yef8DO6+RGqpEXh5Xq+UH9m8C9Vq8LXyvpHUyI9NkeZ4ktP
7UJgMG70g8RM/vuaRFtDKQKBgGHD0qZ82tulUp2bf3cGSOx7JckQWZMDA8OHdMCu
P44LqHDYY92Lwtzw8ow0GpUMdz/g57CJObWJUWAScLLACXTole8OHK7GIwcROEge
hEnnCzjXIEhpZpaKqRs6MIlZpHT9QPAata94pUzhwK2vG4Xn045uuWipZqNfARLN
taGxAoGAQGFYb63lBeGS2vkUyovP2kMwBF0E6Y+3Il+TGjwPalyg+TyNzEAvkOUe
2iy8Eul9rT6qcByzNXnNAMRHYhXDWQWmRaHM/lzyIkNr/O3UBEQKiSew/YhH6s1W
iMwh+x+ekyFOxb98aNqlnEH/7PsQonzWThpzcAAojllTt9AIbbc=
-----END RSA PRIVATE KEY-----"""

_LEAP_DEVICE_TYPES = {'light': ['WallDimmer', 'PlugInDimmer'],
                      'switch': ['WallSwitch'],
                      'cover': ['SerenaHoneycombShade', 'SerenaRollerShade',
                                'TriathlonHoneycombShade',
                                'TriathlonRollerShade', 'QsWirelessShade'],
                      'sensor': ['Pico1Button', 'Pico2Button',
                                 'Pico2ButtonRaiseLower', 'Pico3Button',
                                 'Pico3ButtonRaiseLower', 'Pico4Button',
                                 'Pico4ButtonScene', 'Pico4ButtonZone',
                                 'Pico4Button2Group', 'FourGroupRemote']}
